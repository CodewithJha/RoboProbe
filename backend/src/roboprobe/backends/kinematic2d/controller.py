"""Regulated pure-pursuit unicycle controller (docs/10 §7.1).

Implements: FR-SIM-001
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

from roboprobe.backends.kinematic2d.model import Kinematic2DModel

__all__ = ["pure_pursuit"]


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _closest_index(path: npt.NDArray[np.float64], x: float, y: float) -> int:
    d2 = (path[:, 0] - x) ** 2 + (path[:, 1] - y) ** 2
    return int(np.argmin(d2))


def _lookahead_point(
    path: npt.NDArray[np.float64], x: float, y: float, lookahead_m: float
) -> tuple[float, float]:
    i = _closest_index(path, x, y)
    remaining = path[i:]
    if len(remaining) == 1:
        return float(remaining[0, 0]), float(remaining[0, 1])
    acc = 0.0
    for j in range(1, len(remaining)):
        dx = remaining[j, 0] - remaining[j - 1, 0]
        dy = remaining[j, 1] - remaining[j - 1, 1]
        step = math.hypot(dx, dy)
        if acc + step >= lookahead_m:
            return float(remaining[j, 0]), float(remaining[j, 1])
        acc += step
    return float(remaining[-1, 0]), float(remaining[-1, 1])


def pure_pursuit(
    pose: tuple[float, float, float],
    path: npt.NDArray[np.float64],
    v_max: float,
    min_obstacle_dist: float,
    model: Kinematic2DModel,
) -> tuple[float, float]:
    """Return ``(v, ω)`` tracking ``path``. Empty path yields a stop command."""
    if path.size == 0 or v_max <= 0.0:
        return 0.0, 0.0
    ctrl = model.controller
    x, y, yaw = pose
    tx, ty = _lookahead_point(path, x, y, ctrl.lookahead_m)
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
