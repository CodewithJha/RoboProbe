"""Pinned parameters and sub-spaces (docs/05 §3 ``with_pins``, FR-SCN-007).

A pin fixes a parameter at a value, so the search runs over the remaining free dimensions.
:meth:`ScenarioSpace.with_pins` returns the same space (same ``id`` and ``version``) with the pins
recorded in ``ScenarioSpace.pins``. Pinned ids leave ``params`` and ``dim``, so ``to_unit``,
``from_unit`` and the samplers only see free dimensions. :meth:`ScenarioSpace.nominal_values`
reports pinned values, so :meth:`ScenarioSpace.make_scenario` re-inserts them into a
free-dimension assignment (and rejects any other value for a pinned id). The ``scenario_hash``
therefore covers the pins.

Implements: FR-SCN-007
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from roboprobe.core import errors
from roboprobe.core.types import ParamType, ParamValue
from roboprobe.scenario import normalize
from roboprobe.scenario._documents import document_error

if TYPE_CHECKING:
    from roboprobe.scenario.space import ParameterSpec, ScenarioSpace

__all__ = ["validate_pins"]


def validate_pins(space: ScenarioSpace, pins: Mapping[str, object]) -> dict[str, ParamValue]:
    """Check ``pins`` against ``space`` and return them merged with existing pins, in file order.

    Values are coerced to the parameter type (``2.0`` becomes ``2`` for an int parameter).

    Raises:
        roboprobe.core.errors.ValidationError: If an id is unknown, a value is invalid or out of
            bounds, or no enabled parameter would stay free. Pointers are ``/pins/<param_id>``.
    """
    known = {spec.id: spec for spec in space.parameters}
    issues: list[tuple[str, str]] = [
        (f"/pins/{param_id}", "unknown parameter") for param_id in pins if param_id not in known
    ]
    coerced: dict[str, ParamValue] = {}
    for param_id, value in pins.items():
        spec = known.get(param_id)
        if spec is None:
            continue
        try:
            normalize.to_unit([spec], {param_id: value})
        except errors.ValidationError as exc:
            issues.extend((f"/pins/{param_id}", message) for message in _messages(exc))
            continue
        coerced[param_id] = _coerce(spec, value)
    merged = {**space.pins, **coerced}
    if not issues and all(spec.id in merged for spec in space.parameters if spec.enabled):
        issues.append(("/pins", "at least one enabled parameter must stay free"))
    if issues:
        raise document_error("pins", issues)
    return {spec.id: merged[spec.id] for spec in space.parameters if spec.id in merged}


def _coerce(spec: ParameterSpec, value: object) -> ParamValue:
    if spec.type is ParamType.CATEGORICAL:
        return str(value)
    number = float(value)  # type: ignore[arg-type]  # validated as a real number
    return int(number) if spec.type is ParamType.INT else number


def _messages(exc: errors.ValidationError) -> list[str]:
    raw = exc.context.get("errors")
    items = raw if isinstance(raw, list) else []
    return [str(item["message"]) for item in items if isinstance(item, dict)]
