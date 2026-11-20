"""Per-run scalar metrics stored with every judged episode (docs/08 §6).

Implements: FR-ORC-004
"""

from __future__ import annotations

import numpy as np

from roboprobe.core.settings import OracleThresholds
from roboprobe.core.types import TaskSpec, Trace
from roboprobe.oracles._signals import loc_error_m, t_goal_s

__all__ = ["compute_run_metrics"]


def compute_run_metrics(
    trace: Trace,
    task: TaskSpec,
    *,
    thresholds: OracleThresholds | None = None,
) -> dict[str, float]:
    """Compute the docs/08 §6 metric dict. Extra ``thresholds`` only for ``d_safe``."""
    cfg = thresholds or OracleThresholds()
    d_safe = cfg.clear.d_safe
    if trace.n_samples == 0:
        return {
            "duration_s": 0.0,
            "path_length_m": 0.0,
            "mean_speed": 0.0,
            "max_speed": 0.0,
            "min_clearance_m": 0.0,
            "time_below_d_safe_s": 0.0,
            "max_loc_error_m": 0.0,
            "mean_loc_error_m": 0.0,
            "n_recoveries": 0.0,
            "n_replans": 0.0,
            "goal_reached": 0.0,
            "t_goal_s": -1.0,
            "energy_proxy": 0.0,
            "rtf_mean": -1.0,
        }
    dt = np.diff(trace.t, prepend=trace.t[0])
    dx = np.diff(trace.gt_x, prepend=trace.gt_x[0])
    dy = np.diff(trace.gt_y, prepend=trace.gt_y[0])
    step = np.hypot(dx, dy)
    speed = np.abs(trace.meas_v)
    loc = loc_error_m(trace)
    t_goal = t_goal_s(trace, task)
    below = trace.min_obstacle_dist < d_safe
    time_below = float(np.sum(dt[below])) if trace.n_samples else 0.0
    rec = trace.meta.get("n_recoveries", 0)
    replan = trace.meta.get("n_replans", 0)
    rtf_mean = float(np.mean(trace.rtf)) if trace.rtf is not None else -1.0
    return {
        "duration_s": trace.duration_s,
        "path_length_m": float(np.sum(step[1:])) if trace.n_samples > 1 else 0.0,
        "mean_speed": float(np.mean(speed)),
        "max_speed": float(np.max(speed)),
        "min_clearance_m": float(np.min(trace.min_obstacle_dist)),
        "time_below_d_safe_s": time_below,
        "max_loc_error_m": float(np.max(loc)),
        "mean_loc_error_m": float(np.mean(loc)),
        "n_recoveries": float(rec) if isinstance(rec, int | float) else 0.0,
        "n_replans": float(replan) if isinstance(replan, int | float) else 0.0,
        "goal_reached": 1.0 if t_goal is not None else 0.0,
        "t_goal_s": t_goal if t_goal is not None else -1.0,
        "energy_proxy": float(np.sum(np.square(speed) * dt)),
        "rtf_mean": rtf_mean,
    }
