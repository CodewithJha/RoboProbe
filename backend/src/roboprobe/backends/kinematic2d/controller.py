"""Regulated pure-pursuit unicycle controller (docs/10 §7.1).

Implements: FR-SIM-001
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

from roboprobe.backends.kinematic2d.model import Kinematic2DModel

__all__ = ["path_arclength", "pure_pursuit"]


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def path_arclength(path: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Cumulative arc length along ``path``, shape ``(n,)``."""
    if len(path) == 0:
        return np.zeros(0, dtype=np.float64)
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    return np.concatenate(([0.0], np.cumsum(seg)))


def _closest_index(path: npt.NDArray[np.float64], x: float, y: float) -> int:
    d2 = (path[:, 0] - x) ** 2 + (path[:, 1] - y) ** 2
    return int(np.argmin(d2))


def _lookahead_point(
    path: npt.NDArray[np.float64],
    arclength: npt.NDArray[np.float64],
    x: float,
    y: float,
    lookahead_m: float,
) -> tuple[float, float]:
    i = _closest_index(path, x, y)
    target = arclength[i] + lookahead_m
    j = int(np.searchsorted(arclength, target, side="left"))
    if j >= len(path):
        j = len(path) - 1
    return float(path[j, 0]), float(path[j, 1])


def pure_pursuit(  # noqa: PLR0913,PLR0917
    pose: tuple[float, float, float],
    path: npt.NDArray[np.float64],
    v_max: float,
    min_obstacle_dist: float,
    model: Kinematic2DModel,
    arclength: npt.NDArray[np.float64] | None = None,
) -> tuple[float, float]:
    """Return ``(v, ω)`` tracking ``path``. Empty path yields a stop command."""
    if path.size == 0 or v_max <= 0.0:
        return 0.0, 0.0
    ctrl = model.controller
    x, y, yaw = pose
    s = path_arclength(path) if arclength is None else arclength
    tx, ty = _lookahead_point(path, s, x, y, ctrl.lookahead_m)
    dx = tx - x
    dy = ty - y
    heading = math.atan2(dy, dx)
    alpha = _wrap(heading - yaw)
    ld = max(math.hypot(dx, dy), np.finfo(np.float64).tiny)
    kappa = 2.0 * math.sin(alpha) / ld
    v = v_max / (1.0 + ctrl.curvature_gain_m * abs(kappa))
    if min_obstacle_dist < ctrl.proximity_m:
        v *= min_obstacle_dist / ctrl.proximity_m
    v = max(0.0, v)
    return v, v * kappa
