"""Scenario parameter spaces: models, strict YAML loader and space versioning (docs/05 §3, docs/06).

A space file (``configs/scenario_spaces/*.yaml``) is loaded in four stages, and each stage reports
every problem with a JSON pointer inside one ``ValidationError(code=SPACE_INVALID)``:

1. strict YAML (safe tags only, duplicate keys rejected, optional byte limit; TM-02);
2. JSON Schema ``schemas/scenario_space.schema.json`` (shape);
3. semantic checks: bounds, nominal values, scales, priors, unique ids, constraint references;
4. the referenced task file (``roboprobe.scenario.task``) and its obstacle-placement references.

**Space version.** ``version = sha256(canonical_json(definition))[:12]``, where ``definition`` is
the *parsed* space document with the task document inlined under ``task`` (plus the nominal-path
points), so comment or whitespace edits never change it but any semantic edit to
the space, task or path does. Canonical JSON is :func:`roboprobe.scenario.hashing.canonical_json`
(sorted keys, compact separators, UTF-8, floats rounded to 12 significant digits).

**Scenarios.** :meth:`ScenarioSpace.make_scenario` validates a point (types, bounds, disabled
parameters held at nominal, constraints), normalises value types and attaches its
``scenario_hash``.

Implements: FR-SCN-001, FR-SCN-002, PR-01
"""

from __future__ import annotations

import ast
import functools
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal, Self, cast

import numpy.typing as npt
import pydantic
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_serializer,
    field_validator,
    model_validator,
)

from roboprobe.core import errors
from roboprobe.core.types import ParamType, ParamValue, Scenario, TaskSpec
from roboprobe.scenario import hashing, normalize
from roboprobe.scenario import pins as pins_module
from roboprobe.scenario import task as task_loader
from roboprobe.scenario._documents import (
    document_error,
    json_pointer,
    load_yaml_document,
    read_document,
    validate_document,
)
from roboprobe.scenario.constraints import CompiledConstraint, ConstraintSet, compile_constraint

__all__ = ["Constraint", "ParameterSpec", "PriorSpec", "ScenarioSpace"]

_SCHEMA = "scenario_space"
_CODE = errors.ErrorCode.SPACE_INVALID
_VERSION_HEX_CHARS = 12
_MIN_CHOICES = 2

Issues = list[tuple[str, str]]
"""``(field or JSON pointer, message)`` pairs."""


class _SemanticError(ValueError):
    """Carries field-level issues out of a model validator, so loaders can report pointers."""

    def __init__(self, issues: Issues) -> None:
        super().__init__("; ".join(f"{field}: {message}" for field, message in issues))
        self.issues = issues


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class PriorSpec(_Frozen):
    """Sampling prior of a parameter (docs/06 §2, docs/07 §2).

    ``truncnormal`` needs ``mean`` and ``std > 0``; ``beta`` needs ``a, b > 0``; ``discrete`` needs
    non-negative ``weights`` (their count is checked against the parameter's levels).
    """

    kind: Literal["uniform", "loguniform", "truncnormal", "beta", "discrete"]
    mean: float | None = None
    std: float | None = None
    a: float | None = None
    b: float | None = None
    weights: tuple[Annotated[float, Field(ge=0)], ...] | None = None

    @model_validator(mode="after")
    def _check_kind_arguments(self) -> Self:
        issues: Issues = []
        if self.kind == "truncnormal" and (self.mean is None or not (self.std or 0) > 0):
            issues.append(("std", "truncnormal prior needs mean and std > 0"))
        if self.kind == "beta" and not ((self.a or 0) > 0 and (self.b or 0) > 0):
            issues.append(("a", "beta prior needs a > 0 and b > 0"))
        if self.kind == "discrete" and not (self.weights and sum(self.weights) > 0):
            issues.append(("weights", "discrete prior needs weights with a positive sum"))
        if issues:
            raise _SemanticError(issues)
        return self


class ParameterSpec(_Frozen):
    """One scenario parameter (docs/05 §3, docs/06 §2); semantic checks run on construction."""

    id: str
    name: str
    type: ParamType
    unit: str
    low: float | None = None
    high: float | None = None
    choices: tuple[str, ...] | None = None
    nominal: float | int | str
    prior: PriorSpec
    scale: Literal["linear", "log"] = "linear"
    group: Literal["robot", "environment", "sensor", "comms", "task"]
    description: str = ""
    enabled: bool = True

    @model_validator(mode="after")
    def _check_semantics(self) -> Self:
        issues = (
            self._categorical_issues()
            if self.type is ParamType.CATEGORICAL
            else self._numeric_issues()
        )
        if issues:
            raise _SemanticError(issues)
        return self

    def _categorical_issues(self) -> Issues:
        issues: Issues = []
        choices = self.choices or ()
        if len(choices) < _MIN_CHOICES or len(set(choices)) != len(choices):
            issues.append(("choices", f"needs >= {_MIN_CHOICES} distinct choices"))
        if self.nominal not in choices:
            issues.append(("nominal", f"{self.nominal!r} is not one of the choices"))
        if self.scale != "linear":
            issues.append(("scale", "categorical parameters cannot use a log scale"))
        if self.prior.kind not in {"uniform", "discrete"}:
            issues.append(("prior", "categorical parameters need a uniform or discrete prior"))
        issues.extend(self._weights_issue(len(choices)))
        return issues

    def _numeric_issues(self) -> Issues:
        if self.low is None or self.high is None:
            return [("low", "float/int parameters need low and high")]
        low, high = self.low, self.high
        issues: Issues = []
        if not low < high:
            issues.append(("high", f"high ({high}) must be greater than low ({low})"))
        if self.type is ParamType.INT and not (low.is_integer() and high.is_integer()):
            issues.append(("low", "int parameters need integral bounds"))
        if isinstance(self.nominal, str | bool):
            issues.append(("nominal", "must be a number"))
        else:
            if not low <= self.nominal <= high:
                issues.append(("nominal", f"{self.nominal} is outside [{low}, {high}]"))
            if self.type is ParamType.INT and not float(self.nominal).is_integer():
                issues.append(("nominal", "must be an integer"))
        if (self.scale == "log" or self.prior.kind == "loguniform") and not low > 0:
            issues.append(("low", "log scale / loguniform prior needs low > 0"))
        if self.prior.kind == "discrete":
            if self.type is not ParamType.INT:
                issues.append(("prior", "discrete priors are for int or categorical parameters"))
            elif not issues:
                issues.extend(self._weights_issue(int(high - low) + 1))
        return issues

    def _weights_issue(self, levels: int) -> Issues:
        weights = self.prior.weights
        if weights is not None and len(weights) != levels:
            return [("prior", f"{len(weights)} weights for {levels} levels")]
        return []


class Constraint(_Frozen):
    """Feasibility constraint, e.g. ``robot.max_speed * comms.cmd_delay_ms <= 150``.

    Evaluation goes through the restricted evaluator (:mod:`roboprobe.scenario.constraints`).
    """

    expr: str
    note: str | None = None

    def referenced_ids(self) -> frozenset[str]:
        """Dotted parameter ids used in the expression.

        Raises:
            SyntaxError: If ``expr`` is not a valid Python expression.
        """
        tree = ast.parse(self.expr, mode="eval")
        return frozenset(
            f"{node.value.id}.{node.attr}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        )

    def compile(self) -> CompiledConstraint:
        """Whitelist-compile the expression (vectorised ``evaluate``/``evaluate_batch``).

        Raises:
            roboprobe.core.errors.ValidationError: If the expression is not allowed.
        """
        return compile_constraint(self.expr)


class ScenarioSpace(_Frozen):
    """A validated scenario space with its task (docs/05 §3). Build with :meth:`from_yaml`."""

    id: str
    version: str
    name: str
    description: str = ""
    task_ref: str
    task: TaskSpec
    parameters: tuple[ParameterSpec, ...]
    constraints: tuple[Constraint, ...] = ()
    oracle_thresholds: Literal["default"] | dict[str, JsonValue] = "default"
    pins: Mapping[str, ParamValue] = Field(default_factory=lambda: MappingProxyType({}))
    """Pinned values (FR-SCN-007); set through :meth:`with_pins`, never part of ``version``."""

    @field_validator("pins", mode="after")
    @classmethod
    def _freeze_pins(cls, pins: Mapping[str, ParamValue]) -> Mapping[str, ParamValue]:
        return MappingProxyType(dict(pins))

    @field_serializer("pins")
    def _serialize_pins(self, pins: Mapping[str, ParamValue]) -> dict[str, ParamValue]:
        return dict(pins)

    @property
    def params(self) -> tuple[ParameterSpec, ...]:
        """Free parameters (enabled, not pinned), in file order; they span the search space."""
        return tuple(p for p in self.parameters if p.enabled and p.id not in self.pins)

    @property
    def dim(self) -> int:
        """Search-space dimension ``d`` (number of free parameters)."""
        return len(self.params)

    def with_pins(self, pins: Mapping[str, object]) -> ScenarioSpace:
        """Return this space with ``pins`` added; ``id`` and ``version`` stay the same.

        Raises:
            roboprobe.core.errors.ValidationError: If a pin is unknown, invalid or out of bounds,
                or nothing would stay free.
        """
        merged = pins_module.validate_pins(self, pins)
        return self.model_copy(update={"pins": MappingProxyType(merged)})

    def param(self, param_id: str) -> ParameterSpec:
        """Return the parameter with ``param_id`` (enabled or not).

        Raises:
            roboprobe.core.errors.NotFoundError: If the id is unknown.
        """
        for spec in self.parameters:
            if spec.id == param_id:
                return spec
        msg = f"unknown parameter {param_id!r} in space {self.id}"
        raise errors.NotFoundError(msg, context={"space_id": self.id, "param_id": param_id})

    def nominal_values(self) -> dict[str, ParamValue]:
        """Every parameter's value at nominal with pins applied (disabled ones always stay here)."""
        return {spec.id: self.pins.get(spec.id, spec.nominal) for spec in self.parameters}

    @functools.cached_property
    def _constraint_set(self) -> ConstraintSet:
        # Safe on a frozen model: constraints never change, and cached_property writes to the
        # instance __dict__ directly (pydantic ignores it for fields, equality and dumps).
        return ConstraintSet(tuple(c.compile() for c in self.constraints))

    def constraint_set(self) -> ConstraintSet:
        """Compiled constraints (compiled once per space, then cached)."""
        return self._constraint_set

    def to_unit(self, values: Mapping[str, object]) -> normalize.FloatArray:
        """Encode ``values`` as a unit vector of shape ``(dim,)`` (docs/06 §4.1).

        Raises:
            roboprobe.core.errors.ValidationError: If an enabled value is missing or invalid.
        """
        return normalize.to_unit(self.params, values)

    def to_unit_batch(self, rows: Sequence[Mapping[str, object]]) -> normalize.FloatArray:
        """Encode ``n`` value mappings as a ``(n, dim)`` unit matrix."""
        return normalize.to_unit_batch(self.params, rows)

    def from_unit(self, u: npt.ArrayLike) -> dict[str, ParamValue]:
        """Decode a unit vector of shape ``(dim,)`` into values of the enabled parameters.

        Disabled parameters are omitted; they stay at :meth:`nominal_values`.

        Raises:
            roboprobe.core.errors.ValidationError: If ``u`` has the wrong shape or is not finite.
        """
        return normalize.from_unit(self.params, u)

    def from_unit_batch(self, u: npt.ArrayLike) -> list[dict[str, ParamValue]]:
        """Decode a ``(n, dim)`` unit matrix into ``n`` value mappings."""
        return normalize.from_unit_batch(self.params, u)

    def make_scenario(self, values: Mapping[str, object]) -> Scenario:
        """Validate ``values`` and build the frozen, hashed :class:`Scenario`.

        Enabled parameters missing from ``values`` and every disabled parameter take their nominal
        value; pinned parameters take their pin and may not be set to anything else. Values are
        normalised to their parameter type (``int``, ``float`` or ``str``) so equal points always
        hash equally (e.g. ``2`` and ``2.0`` for a float parameter).

        Raises:
            roboprobe.core.errors.ValidationError: For unknown ids, a disabled parameter set away
                from its nominal value, a pinned parameter set away from its pin, a wrong type or
                out-of-bounds value (every problem is listed in ``context["errors"]``), or a
                violated constraint.
        """
        source = f"scenario in {self.id}"
        merged: dict[str, object] = {**self.nominal_values(), **values}
        known = {spec.id for spec in self.parameters}
        issues = [(f"/{key}", "unknown parameter") for key in values if key not in known]
        held = self.nominal_values()
        issues += [
            (f"/{spec.id}", _held_message(spec, held[spec.id], pinned=spec.id in self.pins))
            for spec in self.parameters
            if (not spec.enabled or spec.id in self.pins)
            and spec.id in values
            and values[spec.id] != held[spec.id]
        ]
        if issues:
            raise document_error(source, issues)
        normalize.to_unit(self.params, merged)  # type and bounds checks with JSON pointers
        normalised = {spec.id: _as_param_type(spec, merged[spec.id]) for spec in self.parameters}
        if not self.is_feasible(normalised):
            violated = [c.expr for c in self.constraints if not c.compile().evaluate(normalised)]
            raise document_error(source, [("", f"violates constraint {e!r}") for e in violated])
        return Scenario(
            space_id=self.id,
            space_version=self.version,
            values=normalised,
            scenario_hash=hashing.scenario_hash(self.version, normalised),
        )

    def nominal(self) -> Scenario:
        """The nominal scenario (every parameter at its nominal value)."""
        return self.make_scenario({})

    def is_feasible(self, values: Mapping[str, ParamValue]) -> bool:
        """Whether ``values`` (parameter units, keyed by id) satisfy every constraint.

        Raises:
            roboprobe.core.errors.ValidationError: If a referenced value is missing.
        """
        return self.constraint_set().is_satisfied(values)

    @classmethod
    def from_yaml(
        cls,
        path: Path,
        *,
        base_dir: Path | None = None,
        max_bytes: int | None = None,
        strict_task: bool = False,
    ) -> ScenarioSpace:
        """Load and validate a space file.

        Args:
            path: Space YAML file.
            base_dir: Directory the ``task`` reference is resolved against (default: working
                directory, like every configured path in docs/27).
            max_bytes: Reject larger files (callers pass ``api.max_upload_mb`` for uploads).
            strict_task: Load the task in strict mode (reject provisional values).

        Raises:
            roboprobe.core.errors.NotFoundError: If ``path`` does not exist.
            roboprobe.core.errors.ValidationError: ``SPACE_INVALID`` with ``context["errors"]``.
        """
        return cls.from_text(
            read_document(path),
            source=str(path),
            base_dir=base_dir,
            max_bytes=max_bytes,
            strict_task=strict_task,
        )

    @classmethod
    def from_text(
        cls,
        text: str | bytes,
        *,
        source: str,
        base_dir: Path | None = None,
        max_bytes: int | None = None,
        strict_task: bool = False,
    ) -> ScenarioSpace:
        """Like :meth:`from_yaml` for in-memory content (e.g. an API upload named ``source``)."""
        document = load_yaml_document(text, source=source, code=_CODE, max_bytes=max_bytes)
        return cls.from_mapping(document, source=source, base_dir=base_dir, strict_task=strict_task)

    @classmethod
    def from_mapping(
        cls,
        document: object,
        *,
        source: str,
        base_dir: Path | None = None,
        strict_task: bool = False,
    ) -> ScenarioSpace:
        """Validate an already-parsed document (YAML or JSON mapping).

        Args:
            document: Parsed document (``yaml.safe_load`` / ``json.loads`` output).
            source: Name used in error messages (file name or ``"<upload>"``).
            base_dir: Directory the ``task`` reference is resolved against.
            strict_task: Load the task in strict mode (reject provisional values).

        Raises:
            roboprobe.core.errors.ValidationError: ``SPACE_INVALID`` with ``context["errors"]``.
        """
        validate_document(document, schema=_SCHEMA, source=source, code=_CODE)
        if not isinstance(document, dict):  # pragma: no cover - the schema requires an object
            raise document_error(source, [("", "space document must be a mapping")], _CODE)
        parameters = _build_parameters(document["parameters"], source)
        constraints = tuple(Constraint.model_validate(c) for c in document.get("constraints", []))
        task_path = _resolve_task_path(document["task"], base_dir or Path(), source)
        task, task_document = _load_task(task_path, source, strict=strict_task)
        _check_references(parameters, constraints, task, source)
        inlined = {**document, "task": task_document}
        return cls(
            id=document["id"],
            version=_space_version(inlined),
            name=document["name"],
            description=document.get("description", ""),
            task_ref=document["task"],
            task=task,
            parameters=parameters,
            constraints=constraints,
            oracle_thresholds=document.get("oracle_thresholds", "default"),
        )


def _as_param_type(spec: ParameterSpec, value: object) -> ParamValue:
    """Normalise a validated value to its parameter's Python type."""
    if spec.type is ParamType.CATEGORICAL:
        return str(value)
    number = float(cast("float", value))  # validated as a real number by normalize.to_unit
    return int(number) if spec.type is ParamType.INT else number


def _build_parameters(raw: list[dict[str, JsonValue]], source: str) -> tuple[ParameterSpec, ...]:
    issues: Issues = []
    specs: list[ParameterSpec] = []
    seen: dict[str, int] = {}
    for index, item in enumerate(raw):
        base = f"/parameters/{index}"
        param_id = str(item["id"])
        if param_id in seen:
            issues.append(
                (f"{base}/id", f"duplicate id {param_id!r} (first at /parameters/{seen[param_id]})")
            )
        seen.setdefault(param_id, index)
        try:
            specs.append(ParameterSpec.model_validate(item))
        except pydantic.ValidationError as exc:
            issues.extend(_pydantic_issues(exc, base))
    if issues:
        raise document_error(source, issues, _CODE)
    return tuple(specs)


def _pydantic_issues(exc: pydantic.ValidationError, base: str) -> Issues:
    issues: Issues = []
    for error in exc.errors():
        location = base + json_pointer(error["loc"])
        cause = error.get("ctx", {}).get("error")
        if isinstance(cause, _SemanticError):
            issues.extend((f"{location}/{field}", message) for field, message in cause.issues)
        else:
            issues.append((location, error["msg"]))
    return issues


def _load_task(path: Path, source: str, *, strict: bool) -> tuple[TaskSpec, dict[str, JsonValue]]:
    try:
        task = task_loader.load_task(path, strict=strict)
        nominal_path = task_loader.load_nominal_path(path, task)
    except (errors.ValidationError, errors.NotFoundError) as exc:
        raise document_error(source, [("/task", str(exc))], _CODE) from exc
    task_document = task.model_dump(mode="json")
    task_document["nominal_path_points"] = nominal_path.tolist()
    return task, task_document


def _check_references(
    parameters: tuple[ParameterSpec, ...],
    constraints: tuple[Constraint, ...],
    task: TaskSpec,
    source: str,
) -> None:
    known = {p.id for p in parameters}
    categorical = {p.id for p in parameters if p.type is ParamType.CATEGORICAL}
    issues: Issues = []
    for index, constraint in enumerate(constraints):
        pointer = f"/constraints/{index}/expr"
        try:
            referenced = constraint.compile().param_ids
        except errors.ValidationError as exc:
            issues.append((pointer, str(exc.context.get("reason", exc))))
            continue
        issues.extend((pointer, f"unknown parameter {ref!r}") for ref in sorted(referenced - known))
        issues.extend(
            (pointer, f"categorical parameter {ref!r} cannot be used in a constraint")
            for ref in sorted(referenced & categorical)
        )
    for index, obstacle in enumerate(task.injected_obstacles):
        for field in ("along", "lateral"):
            ref = getattr(obstacle.placement, field)
            if ref not in known:
                where = f"injected_obstacles/{index}/placement/{field}"
                issues.append(("/task", f"{where}: unknown parameter {ref!r}"))
    if issues:
        raise document_error(source, issues, _CODE)


def _held_message(spec: ParameterSpec, held: ParamValue, *, pinned: bool) -> str:
    if pinned:
        return f"parameter is pinned to {held!r}"
    return f"disabled parameter is held at its nominal value {spec.nominal!r}"


def _resolve_task_path(task_ref: str, base_dir: Path, source: str) -> Path:
    """Resolve ``task`` relative to ``base_dir``, refusing paths that escape it (uploads; TM-02)."""
    root = base_dir.resolve()
    path = (root / task_ref).resolve()
    if Path(task_ref).is_absolute() or not path.is_relative_to(root):
        issue = ("/task", "task path must stay inside the base directory")
        raise document_error(source, [issue], _CODE)
    return path


def _space_version(definition: Mapping[str, object]) -> str:
    return hashing.content_hash(definition, length=_VERSION_HEX_CHARS)
