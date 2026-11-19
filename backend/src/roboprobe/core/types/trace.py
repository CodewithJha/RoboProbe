"""Columnar episode trace (docs/05 §1, docs/11 §6.2).

Implements: FR-RUN-004
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

import numpy as np
import numpy.typing as npt
from pydantic import JsonValue

from roboprobe.core.types.enums import NavStatus

__all__ = ["FloatArray", "Trace"]

# --------------------------------------------------------------------------- trace

FloatArray = npt.NDArray[np.float64]

_FLOAT_COLUMNS: tuple[str, ...] = (
    "t",
    "gt_x",
    "gt_y",
    "gt_yaw",
    "est_x",
    "est_y",
    "est_yaw",
    "cmd_v",
    "cmd_w",
    "meas_v",
    "meas_w",
    "min_obstacle_dist",
    "roll",
    "pitch",
)
_COLUMN_DTYPES: dict[str, np.dtype[np.generic]] = {
    **{name: np.dtype(np.float64) for name in _FLOAT_COLUMNS},
    "contact": np.dtype(np.bool_),
    "nav_status": np.dtype(np.int8),
}
_NAV_STATUS_CODES = np.array([s.value for s in NavStatus], dtype=np.int8)


@dataclass(frozen=True, slots=True, eq=False)
class Trace:
    """Columnar episode trace, one row per sample (>= 10 Hz) (docs/05 §1, docs/11 §6.2).

    Every column is a 1-D array of the same length ``n``. Arrays are stored as read-only views
    and ``meta`` as a read-only mapping copy, so a trace cannot be mutated through its
    attributes (the caller's own array objects are not modified). Units: time [s], positions
    and distances [m], angles [rad], linear velocity [m/s], angular velocity [rad/s].

    Raises:
        ValueError: On wrong dtype or dimensionality, mismatched lengths, a time column that is
            not finite and strictly increasing, unknown ``nav_status`` codes (see
            :class:`~roboprobe.core.types.NavStatus`) or a non-finite goal.
    """

    t: FloatArray
    gt_x: FloatArray
    gt_y: FloatArray
    gt_yaw: FloatArray
    est_x: FloatArray
    est_y: FloatArray
    est_yaw: FloatArray
    cmd_v: FloatArray
    cmd_w: FloatArray
    meas_v: FloatArray
    meas_w: FloatArray
    min_obstacle_dist: FloatArray
    contact: npt.NDArray[np.bool_]
    roll: FloatArray
    pitch: FloatArray
    nav_status: npt.NDArray[np.int8]
    goal_x: float
    goal_y: float
    meta: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate columns and freeze them as read-only views."""
        n = None
        for name, dtype in _COLUMN_DTYPES.items():
            column = getattr(self, name)
            if not isinstance(column, np.ndarray) or column.ndim != 1:
                msg = f"Trace.{name} must be a 1-D numpy array"
                raise ValueError(msg)
            if column.dtype != dtype:
                msg = f"Trace.{name} must have dtype {dtype}, got {column.dtype}"
                raise ValueError(msg)
            if n is None:
                n = column.shape[0]
            elif column.shape[0] != n:
                msg = f"Trace.{name} has length {column.shape[0]}, expected {n} (length of t)"
                raise ValueError(msg)
            view = column.view()
            view.flags.writeable = False
            object.__setattr__(self, name, view)
        if not np.all(np.isfinite(self.t)) or np.any(np.diff(self.t) <= 0):
            msg = "Trace.t must be finite and strictly increasing"
            raise ValueError(msg)
        if not np.all(np.isin(self.nav_status, _NAV_STATUS_CODES)):
            msg = f"Trace.nav_status contains codes outside {_NAV_STATUS_CODES.tolist()}"
            raise ValueError(msg)
        for name in ("goal_x", "goal_y"):
            value = float(getattr(self, name))
            if not math.isfinite(value):
                msg = f"Trace.{name} must be finite, got {value!r}"
                raise ValueError(msg)
            object.__setattr__(self, name, value)
        object.__setattr__(self, "meta", MappingProxyType(dict(self.meta)))

    @property
    def n_samples(self) -> int:
        """Number of samples (rows)."""
        return int(self.t.shape[0])

    @property
    def duration_s(self) -> float:
        """Elapsed simulated time between the first and last sample [s]; 0 if < 2 samples."""
        if self.n_samples == 0:
            return 0.0
        return float(self.t[-1] - self.t[0])
