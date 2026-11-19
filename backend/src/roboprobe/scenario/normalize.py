"""Normalisation between parameter values and the unit hypercube ``[0, 1]^d`` (docs/06 §4.1).

Each enabled parameter maps to one coordinate of ``u``:

- float, linear: ``u = (x - low) / (high - low)``;
- float, log: ``u = (ln x - ln low) / (ln high - ln low)``;
- int, ``n = high - low + 1`` bins: ``u = (x - low + 0.5) / n``; inverse ``low + floor(u*n)``;
- categorical, ``k`` choices: ``u = (i + 0.5) / k``; inverse ``choices[min(k - 1, floor(u*k))]``.

Ints and categoricals map to bin centres, so they round-trip exactly. Floats round-trip to within
floating-point error, and decoded values are clipped to ``[low, high]``. Values are validated
before encoding, and every problem is reported in one ``ValidationError``. Finite unit coordinates
outside ``[0, 1]`` are clipped with a ``scenario.unit_clipped`` warning; non-finite ones are
rejected.

These functions are pure and take the parameter list explicitly; ``ScenarioSpace.to_unit`` and
``ScenarioSpace.from_unit`` delegate here with ``space.params``.

Implements: FR-SCN-003
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from numbers import Integral, Real
from typing import TYPE_CHECKING, cast

import numpy as np
import numpy.typing as npt
import structlog

from roboprobe.core import errors
from roboprobe.core.types import ParamType, ParamValue
from roboprobe.scenario._documents import document_error

if TYPE_CHECKING:
    from roboprobe.scenario.space import ParameterSpec

__all__ = ["from_unit", "from_unit_batch", "to_unit", "to_unit_batch"]

_log = structlog.get_logger(__name__)
_BIN_CENTRE = 0.5
_BATCH_NDIM = 2

FloatArray = npt.NDArray[np.float64]


def to_unit(params: Sequence[ParameterSpec], values: Mapping[str, object]) -> FloatArray:
    """Encode one value mapping as a unit vector of shape ``(d,)``.

    Args:
        params: The enabled parameters, in order (``ScenarioSpace.params``).
        values: ``{param_id: value}``; keys outside ``params`` are ignored.

    Raises:
        roboprobe.core.errors.ValidationError: If a value is missing, has the wrong type or is
            out of bounds. ``context["errors"]`` lists every problem with pointer ``/<param_id>``.
    """
    vector: FloatArray = to_unit_batch(params, [values])[0]
    return vector


def to_unit_batch(
    params: Sequence[ParameterSpec], rows: Sequence[Mapping[str, object]]
) -> FloatArray:
    """Encode ``n`` value mappings as a unit matrix of shape ``(n, d)`` (see :func:`to_unit`)."""
    issues: list[tuple[str, str]] = []
    out = np.empty((len(rows), len(params)), dtype=np.float64)
    for row_index, row in enumerate(rows):
        prefix = f"/{row_index}" if len(rows) > 1 else ""
        for col, spec in enumerate(params):
            pointer = f"{prefix}/{spec.id}"
            if spec.id not in row:
                issues.append((pointer, "missing value"))
                continue
            problem = _value_problem(spec, row[spec.id])
            if problem is not None:
                issues.append((pointer, problem))
                continue
            out[row_index, col] = _encode(spec, cast("ParamValue", row[spec.id]))
    if issues:
        raise _error("values", issues)
    return out


def from_unit(params: Sequence[ParameterSpec], u: npt.ArrayLike) -> dict[str, ParamValue]:
    """Decode a unit vector of shape ``(d,)`` into ``{param_id: value}`` for ``params``.

    Raises:
        roboprobe.core.errors.ValidationError: If ``u`` has the wrong shape or a non-finite entry.
    """
    vector = np.asarray(u, dtype=np.float64)
    if vector.ndim != 1:
        raise _error("u", [("", f"expected shape ({len(params)},), got {vector.shape}")])
    return from_unit_batch(params, vector[np.newaxis, :])[0]


def from_unit_batch(
    params: Sequence[ParameterSpec], u: npt.ArrayLike
) -> list[dict[str, ParamValue]]:
    """Decode a unit matrix of shape ``(n, d)`` into ``n`` mappings (see :func:`from_unit`)."""
    matrix = np.asarray(u, dtype=np.float64)
    if matrix.ndim != _BATCH_NDIM or matrix.shape[1] != len(params):
        raise _error("u", [("", f"expected shape (n, {len(params)}), got {matrix.shape}")])
    if not np.all(np.isfinite(matrix)):
        raise _error("u", [("", "unit coordinates must be finite")])
    outside = (matrix < 0.0) | (matrix > 1.0)
    if np.any(outside):
        _log.warning(
            "scenario.unit_clipped",
            count=int(np.count_nonzero(outside)),
            min=float(matrix.min()),
            max=float(matrix.max()),
        )
        matrix = np.clip(matrix, 0.0, 1.0)
    rows: list[dict[str, ParamValue]] = [{} for _ in range(matrix.shape[0])]
    for col, spec in enumerate(params):
        for row, value in zip(rows, _decode_column(spec, matrix[:, col]), strict=True):
            row[spec.id] = value
    return rows


def _value_problem(spec: ParameterSpec, value: object) -> str | None:
    """Return why ``value`` is not acceptable for ``spec``, or ``None``."""
    if spec.type is ParamType.CATEGORICAL:
        choices = spec.choices or ()
        if isinstance(value, str) and value in choices:
            return None
        return f"{value!r} is not one of {list(choices)}"
    if isinstance(value, bool) or not isinstance(value, Real):
        return f"expected a number, got {type(value).__name__}"
    return _number_problem(spec, value)


def _number_problem(spec: ParameterSpec, value: Real) -> str | None:
    number = float(value)
    if not math.isfinite(number):
        return "value must be finite"
    if spec.type is ParamType.INT and not (isinstance(value, Integral) or number.is_integer()):
        return f"{value!r} is not an integer"
    low, high = _bounds(spec)
    if not low <= number <= high:
        return f"{value!r} is outside [{low:g}, {high:g}]"
    return None


def _bounds(spec: ParameterSpec) -> tuple[float, float]:
    # Guaranteed by ParameterSpec's semantic checks for numeric parameters.
    if spec.low is None or spec.high is None:  # pragma: no cover - defensive
        msg = f"parameter {spec.id} has no bounds"
        raise errors.ValidationError(msg)
    return spec.low, spec.high


def _encode(spec: ParameterSpec, value: ParamValue) -> float:
    if spec.type is ParamType.CATEGORICAL:
        choices = spec.choices or ()
        return (choices.index(str(value)) + _BIN_CENTRE) / len(choices)
    low, high = _bounds(spec)
    number = float(value)
    if spec.type is ParamType.INT:
        return (number - low + _BIN_CENTRE) / (high - low + 1)
    if spec.scale == "log":
        return (math.log(number) - math.log(low)) / (math.log(high) - math.log(low))
    return (number - low) / (high - low)


def _decode_column(spec: ParameterSpec, u: FloatArray) -> list[ParamValue]:
    if spec.type is ParamType.CATEGORICAL:
        choices = spec.choices or ()
        index = np.minimum(len(choices) - 1, np.floor(u * len(choices)).astype(np.int64))
        return [choices[i] for i in index.tolist()]
    low, high = _bounds(spec)
    if spec.type is ParamType.INT:
        bins = high - low + 1
        ints = np.minimum(high, low + np.floor(u * bins))
        return [int(x) for x in ints.tolist()]
    if spec.scale == "log":
        x = np.exp(math.log(low) + u * (math.log(high) - math.log(low)))
    else:
        x = low + u * (high - low)
    return [float(v) for v in np.clip(x, low, high).tolist()]


def _error(source: str, issues: list[tuple[str, str]]) -> errors.ValidationError:
    return document_error(source, issues)
