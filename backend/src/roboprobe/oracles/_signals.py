"""Shared vectorised trace helpers for oracles (docs/08 §3).

Implements: FR-ORC-001
"""

from __future__ import annotations

from typing import Final

import numpy as np
import numpy.typing as npt

from roboprobe.core.types import NavStatus, TaskSpec, Trace

# docs/06 P1 nominal max speed; T_max fallback when a trace has no commanded speed.
P1_NOMINAL_MAX_SPEED_MPS: Final[float] = 0.26

__all__ = [
    "P1_NOMINAL_MAX_SPEED_MPS",
    "at_goal",
    "clip",
    "loc_error_m",
    "measured_speed",
    "nav_active",
    "nominal_polyline",
    "remaining_path_length_m",
    "t_goal_s",
    "wrap_angle",
    "yaw_error",
]


def clip(z: npt.ArrayLike) -> npt.NDArray[np.float64]:
    """Clip robustness to ``[-1, 1]`` (docs/08 §3)."""
    return np.clip(np.asarray(z, dtype=np.float64), -1.0, 1.0)


def wrap_angle(rad: npt.ArrayLike) -> npt.NDArray[np.float64]:
    """Wrap angle(s) to ``(-π, π]``."""
    return np.arctan2(np.sin(rad), np.cos(rad))


def yaw_error(yaw: npt.NDArray[np.float64], target: float) -> npt.NDArray[np.float64]:
    """Smallest signed yaw error relative to ``target`` [rad]."""
    return wrap_angle(yaw - target)


def at_goal(trace: Trace, task: TaskSpec) -> npt.NDArray[np.bool_]:
    """Per-sample goal acceptance using task pose and tolerances (docs/08 §3.2)."""
    pos = np.hypot(trace.gt_x - task.goal.x, trace.gt_y - task.goal.y)
    yaw = np.abs(yaw_error(trace.gt_yaw, task.goal.yaw))
    return (pos <= task.goal_tolerance.xy) & (yaw <= task.goal_tolerance.yaw)


def t_goal_s(trace: Trace, task: TaskSpec) -> float | None:
    """First sample time at the goal, or ``None`` if never reached."""
    hits = at_goal(trace, task)
    if not np.any(hits):
        return None
    return float(trace.t[int(np.argmax(hits))])


def nav_active(trace: Trace) -> npt.NDArray[np.bool_]:
    """Samples whose Nav2 action is ACTIVE."""
    return np.asarray(trace.nav_status == np.int8(NavStatus.ACTIVE), dtype=np.bool_)


def measured_speed(trace: Trace) -> npt.NDArray[np.float64]:
    """Absolute measured linear speed [m/s]."""
    return np.abs(trace.meas_v)


def loc_error_m(trace: Trace) -> npt.NDArray[np.float64]:
    """Planar localisation error between ground truth and estimate [m]."""
    return np.hypot(trace.gt_x - trace.est_x, trace.gt_y - trace.est_y)


def nominal_polyline(task: TaskSpec) -> npt.NDArray[np.float64]:
    """Two-point nominal path from task start to goal (shape ``(2, 2)``)."""
    return np.array([[task.start.x, task.start.y], [task.goal.x, task.goal.y]], dtype=np.float64)


def remaining_path_length_m(
    x: npt.ArrayLike,
    y: npt.ArrayLike,
    polyline: npt.NDArray[np.float64],
) -> npt.NDArray[np.float64]:
    """Remaining polyline length from the closest point on ``polyline`` to the goal.

    ``polyline`` has shape ``(m, 2)``. Result is one remaining length per query point.
    """
    px = np.asarray(x, dtype=np.float64).reshape(-1)
    py = np.asarray(y, dtype=np.float64).reshape(-1)
    pts = np.stack([px, py], axis=1)
    segs = polyline[1:] - polyline[:-1]
    seg_len = np.linalg.norm(segs, axis=1)
    total = float(np.sum(seg_len))
    if polyline.shape[0] < 2 or total == 0.0:  # noqa: PLR2004
        return np.asarray(np.hypot(px - polyline[-1, 0], py - polyline[-1, 1]), dtype=np.float64)

    best_d2 = np.full(pts.shape[0], np.inf, dtype=np.float64)
    best_remaining = np.zeros(pts.shape[0], dtype=np.float64)
    suffix = np.concatenate([np.cumsum(seg_len[::-1])[::-1][1:], np.zeros(1)])
    for a, ab, length, after in zip(polyline[:-1], segs, seg_len, suffix, strict=True):
        if length == 0.0:
            t = np.zeros(pts.shape[0])
            closest = np.broadcast_to(a, pts.shape)
        else:
            t = np.clip(np.sum((pts - a) * ab, axis=1) / (length * length), 0.0, 1.0)
            closest = a + t[:, None] * ab
        d2 = np.sum((pts - closest) ** 2, axis=1)
        remaining = (1.0 - t) * length + after
        better = d2 < best_d2
        best_d2 = np.where(better, d2, best_d2)
        best_remaining = np.where(better, remaining, best_remaining)
    return best_remaining
