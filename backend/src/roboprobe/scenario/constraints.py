"""Restricted constraint evaluator and rejection sampling (docs/06 §4, docs/31 TM-02).

A constraint is a boolean expression over dotted parameter ids, e.g.
``robot.max_speed * comms.cmd_delay_ms <= 150``. Expressions come from user-supplied space files,
so they are **never** passed to ``eval``/``compile``: :func:`compile_constraint` parses with
``ast.parse(mode="eval")``, checks every node against an explicit whitelist and builds a closure
over NumPy operations. Anything outside the grammar below is rejected at load time with
:class:`~roboprobe.core.errors.ValidationError`.

Grammar (``num`` and ``bool`` are checked statically, so ``1 + (a.b < 2)`` is rejected)::

    bool := num CMP num [CMP num ...] | bool and/or bool | not bool | (bool)
    num  := NUMBER | group.param | num (+ - * / **) num | -num | +num
          | abs(num) | min(num, num, ...) | max(num, num, ...) | (num)

Evaluation is vectorised: parameter values may be scalars or equal-length 1-D arrays, so a
whole ``(n, d)`` batch is checked in one call. Floating-point edge cases (division by zero,
overflow) never raise; they produce ``inf``/``nan`` and any comparison involving ``nan`` is
``False`` (infeasible).

Layer: Domain (L2).

Implements: FR-SCN-004, NFR-SEC-003
"""

from __future__ import annotations

import ast
import itertools
import operator
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol

import numpy as np
import numpy.typing as npt

from roboprobe.core import errors
from roboprobe.core.settings.scenario import ScenarioSettings

__all__ = [
    "BatchSampler",
    "CompiledConstraint",
    "ConstraintSet",
    "Feasibility",
    "compile_constraint",
    "rejection_sample",
]

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]
_Values = Mapping[str, FloatArray]
_NumFn = Callable[[_Values], FloatArray]
_BoolFn = Callable[[_Values], BoolArray]
_Kind = Literal["num", "bool"]

_PARAM_ID: Final = re.compile(r"[a-z]+\.[a-z0-9_]+")
"""Mirrors the ``param_id`` pattern of ``schemas/scenario_space.schema.json``."""

_BIN_OPS: Final[Mapping[type[ast.operator], Callable[[FloatArray, FloatArray], FloatArray]]] = {
    ast.Add: np.add,
    ast.Sub: np.subtract,
    ast.Mult: np.multiply,
    ast.Div: np.divide,
    ast.Pow: np.power,
}
_COMPARE_OPS: Final[Mapping[type[ast.cmpop], Callable[[FloatArray, FloatArray], BoolArray]]] = {
    ast.Lt: np.less,
    ast.LtE: np.less_equal,
    ast.Gt: np.greater,
    ast.GtE: np.greater_equal,
    ast.Eq: np.equal,
    ast.NotEq: np.not_equal,
}
_FUNCTIONS: Final[Mapping[str, tuple[int, int | None, Callable[..., FloatArray]]]] = {
    # name -> (minimum, maximum or None = unbounded argument count, implementation)
    "abs": (1, 1, np.abs),
    "min": (2, None, lambda *xs: np.minimum.reduce(np.broadcast_arrays(*xs))),
    "max": (2, None, lambda *xs: np.maximum.reduce(np.broadcast_arrays(*xs))),
}


def _invalid(expr: str, message: str) -> errors.ValidationError:
    return errors.ValidationError(
        f"invalid constraint {expr!r}: {message}", context={"expr": expr, "reason": message}
    )


def default_max_literal_exponent() -> int:
    """Return the configured cap on literal constraint exponents (TM-03)."""
    value = ScenarioSettings.model_fields["constraint_max_literal_exponent"].default
    if not isinstance(value, int):
        msg = "constraint_max_literal_exponent default must be an int"
        raise TypeError(msg)
    return value


def _exponent_rejected(node: ast.AST, limit: int) -> bool:
    """True when a power's exponent contains an oversized integer literal.

    Float literals stay allowed: they are already ``float64`` and ``np.power`` overflows in
    constant time. Integer literals above ``limit`` are rejected before that conversion.
    """
    for child in ast.walk(node):
        value = child.value if isinstance(child, ast.Constant) else None
        if isinstance(value, int) and not isinstance(value, bool) and abs(value) > limit:
            return True
    return False


class _Compiler:
    """Single-use whitelist compiler; collects referenced parameter ids while compiling."""

    def __init__(self, expr: str, *, max_literal_exponent: int) -> None:
        self.expr = expr
        self.max_literal_exponent = max_literal_exponent
        self.param_ids: set[str] = set()

    def compile(self, node: ast.expr) -> tuple[_Kind, _NumFn | _BoolFn]:
        handler = getattr(self, f"_{type(node).__name__}", None)
        if handler is None:
            raise self._reject(node, f"{type(node).__name__} is not allowed")
        result: tuple[_Kind, _NumFn | _BoolFn] = handler(node)
        return result

    def num(self, node: ast.expr) -> _NumFn:
        kind, fn = self.compile(node)
        if kind != "num":
            raise self._reject(node, "expected a number, got a boolean expression")
        return fn  # type: ignore[return-value]

    def boolean(self, node: ast.expr) -> _BoolFn:
        kind, fn = self.compile(node)
        if kind != "bool":
            raise self._reject(node, "expected a comparison or boolean expression")
        return fn  # type: ignore[return-value]

    def _reject(self, node: ast.AST, message: str) -> errors.ValidationError:
        column = getattr(node, "col_offset", None)
        where = f" at column {column + 1}" if column is not None else ""
        return _invalid(self.expr, f"{message}{where}")

    # -- numbers -------------------------------------------------------------------------------
    def _Constant(self, node: ast.Constant) -> tuple[_Kind, _NumFn]:  # noqa: N802 - ast node name
        value = node.value
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise self._reject(node, f"only numeric literals are allowed, got {value!r}")
        constant: FloatArray = np.asarray(value, dtype=np.float64)
        return "num", lambda _values: constant

    def _Attribute(self, node: ast.Attribute) -> tuple[_Kind, _NumFn]:  # noqa: N802
        if not isinstance(node.value, ast.Name):
            raise self._reject(node, "attribute access is only allowed as a parameter id")
        if node.attr.startswith("_"):
            raise self._reject(node, f"names starting with '_' are not allowed ({node.attr!r})")
        param_id = f"{node.value.id}.{node.attr}"
        if not _PARAM_ID.fullmatch(param_id):
            raise self._reject(node, f"{param_id!r} is not a valid parameter id")
        self.param_ids.add(param_id)
        return "num", operator.itemgetter(param_id)

    def _BinOp(self, node: ast.BinOp) -> tuple[_Kind, _NumFn]:  # noqa: N802
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise self._reject(node, f"operator {type(node.op).__name__} is not allowed")
        if isinstance(node.op, ast.Pow) and _exponent_rejected(
            node.right, self.max_literal_exponent
        ):
            raise self._reject(
                node,
                f"integer exponent exceeds {self.max_literal_exponent}",
            )
        left, right = self.num(node.left), self.num(node.right)
        return "num", lambda values: op(left(values), right(values))

    def _UnaryOp(self, node: ast.UnaryOp) -> tuple[_Kind, _NumFn | _BoolFn]:  # noqa: N802
        if isinstance(node.op, ast.Not):
            operand_bool = self.boolean(node.operand)
            return "bool", lambda values: np.logical_not(operand_bool(values))
        if isinstance(node.op, ast.USub):
            operand = self.num(node.operand)
            return "num", lambda values: np.negative(operand(values))
        if isinstance(node.op, ast.UAdd):
            return "num", self.num(node.operand)
        raise self._reject(node, f"operator {type(node.op).__name__} is not allowed")

    def _Call(self, node: ast.Call) -> tuple[_Kind, _NumFn]:  # noqa: N802
        name = node.func.id if isinstance(node.func, ast.Name) else None
        spec = _FUNCTIONS.get(name) if name is not None else None
        if name is None or spec is None:
            allowed = ", ".join(sorted(_FUNCTIONS))
            raise self._reject(node, f"only calls to {allowed} are allowed")
        min_args, max_args, fn = spec
        if node.keywords or any(isinstance(a, ast.Starred) for a in node.args):
            raise self._reject(node, f"{name}() takes positional arguments only")
        if len(node.args) < min_args or (max_args is not None and len(node.args) > max_args):
            raise self._reject(node, f"wrong number of arguments to {name}()")
        args = [self.num(arg) for arg in node.args]
        return "num", lambda values: fn(*(arg(values) for arg in args))

    # -- booleans ------------------------------------------------------------------------------
    def _Compare(self, node: ast.Compare) -> tuple[_Kind, _BoolFn]:  # noqa: N802
        ops = []
        for op in node.ops:
            compare = _COMPARE_OPS.get(type(op))
            if compare is None:
                raise self._reject(node, f"comparison {type(op).__name__} is not allowed")
            ops.append(compare)
        operands = [self.num(node.left), *(self.num(c) for c in node.comparators)]

        def evaluate(values: _Values) -> BoolArray:
            evaluated = [operand(values) for operand in operands]
            pairs = zip(ops, itertools.pairwise(evaluated), strict=True)
            return np.logical_and.reduce([cmp(a, b) for cmp, (a, b) in pairs])  # type: ignore[no-any-return]

        return "bool", evaluate

    def _BoolOp(self, node: ast.BoolOp) -> tuple[_Kind, _BoolFn]:  # noqa: N802
        combine = np.logical_and if isinstance(node.op, ast.And) else np.logical_or
        parts = [self.boolean(value) for value in node.values]
        return "bool", lambda values: combine.reduce([part(values) for part in parts])


@dataclass(frozen=True, slots=True, eq=False)
class CompiledConstraint:
    """A whitelisted, vectorised constraint. Build with :func:`compile_constraint`."""

    expr: str
    param_ids: frozenset[str]
    _predicate: _BoolFn

    def evaluate(self, values: Mapping[str, npt.ArrayLike]) -> BoolArray:
        """Evaluate on scalar or 1-D array values (one entry per referenced parameter id).

        Returns:
            A boolean array broadcast over the inputs (0-d for scalar inputs).

        Raises:
            roboprobe.core.errors.ValidationError: If a referenced value is missing or not numeric.
        """
        columns: dict[str, FloatArray] = {}
        for param_id in self.param_ids:
            if param_id not in values:
                msg = f"constraint {self.expr!r} needs a value for {param_id!r}"
                raise errors.ValidationError(msg, context={"expr": self.expr, "param_id": param_id})
            columns[param_id] = _as_float(values[param_id], self.expr, param_id)
        try:
            with np.errstate(all="ignore"):
                return np.asarray(self._predicate(columns), dtype=np.bool_)
        except RecursionError as exc:  # pragma: no cover - compile-time depth check bounds this
            raise _invalid(self.expr, "expression is nested too deeply") from exc

    def evaluate_batch(self, batch: npt.ArrayLike, columns: Sequence[str]) -> BoolArray:
        """Evaluate every row of an ``(n, d)`` batch whose column ``j`` holds ``columns[j]``.

        Returns:
            Boolean mask of shape ``(n,)``.
        """
        matrix = _as_matrix(batch, columns)
        mask = self.evaluate({cid: matrix[:, j] for j, cid in enumerate(columns)})
        return np.broadcast_to(mask, (matrix.shape[0],)).copy()


def compile_constraint(expr: str, *, max_literal_exponent: int | None = None) -> CompiledConstraint:
    """Parse and whitelist-compile ``expr`` (see the module grammar); never executes Python code.

    Args:
        expr: Boolean constraint over dotted parameter ids.
        max_literal_exponent: Cap on literal exponents. The scenario setting when omitted.

    Raises:
        roboprobe.core.errors.ValidationError: For syntax errors and any disallowed construct.
    """
    limit = default_max_literal_exponent() if max_literal_exponent is None else max_literal_exponent
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise _invalid(expr, f"invalid expression: {exc.msg}") from exc
    except (ValueError, RecursionError, MemoryError) as exc:  # null bytes, absurd nesting
        raise _invalid(expr, f"invalid expression: {type(exc).__name__}") from exc
    compiler = _Compiler(expr, max_literal_exponent=limit)
    try:
        predicate = compiler.boolean(tree.body)
    except RecursionError as exc:
        raise _invalid(expr, "expression is nested too deeply") from exc
    return CompiledConstraint(
        expr=expr, param_ids=frozenset(compiler.param_ids), _predicate=predicate
    )


@dataclass(frozen=True, slots=True)
class ConstraintSet:
    """Conjunction of constraints; an empty set accepts everything."""

    constraints: tuple[CompiledConstraint, ...] = ()

    @classmethod
    def compile(cls, expressions: Collection[str]) -> ConstraintSet:
        """Compile every expression (first failure raises ``ValidationError``)."""
        return cls(tuple(compile_constraint(expr) for expr in expressions))

    @property
    def param_ids(self) -> frozenset[str]:
        """Union of the parameter ids referenced by all constraints."""
        return frozenset().union(*(c.param_ids for c in self.constraints))

    def is_satisfied(self, values: Mapping[str, npt.ArrayLike]) -> bool:
        """Whether a single point satisfies every constraint."""
        return all(bool(np.all(c.evaluate(values))) for c in self.constraints)

    def mask(self, batch: npt.ArrayLike, columns: Sequence[str]) -> BoolArray:
        """Feasibility mask of shape ``(n,)`` for an ``(n, d)`` batch (see ``evaluate_batch``)."""
        matrix = _as_matrix(batch, columns)
        result = np.ones(matrix.shape[0], dtype=np.bool_)
        for constraint in self.constraints:
            result &= constraint.evaluate_batch(matrix, columns)
        return result


class BatchSampler(Protocol):
    """Anything that draws an ``(n, d)`` batch; matches the docs/05 §3 ``Sampler`` protocol."""

    def sample(self, n: int, rng: np.random.Generator) -> FloatArray:
        """Draw ``n`` points."""
        ...


Feasibility = Callable[[FloatArray], BoolArray]
"""Maps an ``(n, d)`` batch (in the sampler's coordinates) to an ``(n,)`` feasibility mask."""


def rejection_sample(
    sampler: BatchSampler,
    feasible: Feasibility,
    n: int,
    rng: np.random.Generator,
    *,
    max_attempts: int,
) -> FloatArray:
    """Draw ``n`` feasible points, keeping draw order, by repeatedly sampling the shortfall.

    Deterministic for a given ``rng`` state. Callers pass ``scenario.constraint_max_attempts`` as
    ``max_attempts`` and a ``feasible`` that decodes the batch to parameter units (for unit-cube
    samplers) before applying a :class:`ConstraintSet`.

    Args:
        sampler: Batch source, e.g. a unit-cube sampler.
        feasible: Feasibility mask function for a batch.
        n: Number of points wanted (``>= 1``).
        rng: Random generator handed to ``sampler``.
        max_attempts: Maximum number of ``sampler.sample`` calls (``>= 1``).

    Returns:
        An ``(n, d)`` array of feasible points.

    Raises:
        roboprobe.core.errors.ValidationError: If ``n``/``max_attempts`` are not positive or fewer
            than ``n`` feasible points were found within ``max_attempts`` draws.
    """
    if n < 1 or max_attempts < 1:
        msg = f"rejection_sample needs n >= 1 and max_attempts >= 1 (got n={n}, {max_attempts=})"
        raise errors.ValidationError(msg, context={"n": n, "max_attempts": max_attempts})
    accepted: list[FloatArray] = []
    found = 0
    for _ in range(max_attempts):
        batch = np.asarray(sampler.sample(n - found, rng), dtype=np.float64)
        keep = batch[np.asarray(feasible(batch), dtype=np.bool_)]
        accepted.append(keep)
        found += keep.shape[0]
        if found >= n:
            return np.concatenate(accepted)[:n]
    msg = f"only {found} of {n} feasible points after {max_attempts} sampling attempts"
    raise errors.ValidationError(
        msg, context={"found": found, "wanted": n, "max_attempts": max_attempts}
    )


def _as_float(value: npt.ArrayLike, expr: str, param_id: str) -> FloatArray:
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        msg = f"constraint {expr!r}: value of {param_id!r} is not numeric"
        raise errors.ValidationError(msg, context={"expr": expr, "param_id": param_id}) from exc
    if array.ndim > 1:
        msg = f"constraint {expr!r}: value of {param_id!r} must be a scalar or 1-D array"
        raise errors.ValidationError(msg, context={"expr": expr, "param_id": param_id})
    return array


def _as_matrix(batch: npt.ArrayLike, columns: Sequence[str]) -> FloatArray:
    matrix = np.asarray(batch, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] != len(columns):  # noqa: PLR2004 - (n, d) shape
        msg = f"expected an (n, {len(columns)}) batch, got shape {matrix.shape}"
        raise errors.ValidationError(msg, context={"shape": list(matrix.shape)})
    return matrix
