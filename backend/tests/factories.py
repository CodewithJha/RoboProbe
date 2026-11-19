"""Builders for valid, frozen domain objects (docs/18 §5): plain functions with keyword overrides.

Every builder returns a fully valid object; pass keyword overrides to vary only what a test cares
about. Overrides go through the model's own validation, so an invalid override fails loudly at
construction time instead of producing an impossible object. Append new builders here (keep them
small and dependency-free); no shared mutable state, so the module is ``pytest-xdist`` safe.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import numpy as np
import numpy.typing as npt
from pydantic import JsonValue

from roboprobe.core.types import (
    FailureClass,
    NavStatus,
    Observation,
    OracleResult,
    RunOutcome,
    Scenario,
    Trace,
    Verdict,
)

__all__ = [
    "DEFAULT_CLEARANCE_M",
    "DEFAULT_DT_S",
    "DEFAULT_PATH_LENGTH_M",
    "DEFAULT_SPEED_MPS",
    "DEFAULT_TRACE_SAMPLES",
    "make_observation",
    "make_oracle_result",
    "make_run_outcome",
    "make_scenario",
    "make_trace",
]

DEFAULT_TRACE_SAMPLES = 101
"""Samples in a synthetic trace (10 s at the default rate)."""
DEFAULT_DT_S = 0.1
"""Synthetic sample period [s] (10 Hz, the minimum trace rate of docs/05 §1)."""
DEFAULT_SPEED_MPS = 0.5
"""Constant forward speed of the synthetic straight-line run [m/s]."""
DEFAULT_CLEARANCE_M = 1.0
"""Constant distance to the nearest obstacle in the synthetic run [m]."""
DEFAULT_PATH_LENGTH_M = DEFAULT_SPEED_MPS * DEFAULT_DT_S * (DEFAULT_TRACE_SAMPLES - 1)
"""Distance covered by the default synthetic run (``n`` samples span ``n - 1`` periods) [m]."""


def make_scenario(**overrides: Any) -> Scenario:
    """Build a :class:`Scenario` in the ``warehouse_v1`` space."""
    fields: dict[str, Any] = {
        "space_id": "warehouse_v1",
        "space_version": "0123456789ab",
        "values": {"robot.max_speed": 0.5, "sensor.lidar_noise_std": 0.01, "obstacle.count": 2},
        "scenario_hash": "f" * 64,
    }
    return Scenario.model_validate(fields | overrides)


def make_observation(**overrides: Any) -> Observation:
    """Build a passing :class:`Observation` (override ``verdict``/``robustness`` together)."""
    fields: dict[str, Any] = {
        "x_unit": (0.25, 0.5, 0.75),
        "robustness": 0.4,
        "verdict": Verdict.PASS,
        "failure_class": None,
        "run_id": uuid4(),
    }
    return Observation.model_validate(fields | overrides)


def make_oracle_result(**overrides: Any) -> OracleResult:
    """Build a satisfied clearance :class:`OracleResult`."""
    fields: dict[str, Any] = {
        "oracle_id": "clearance",
        "failure_class": FailureClass.COL,
        "severity": "failure",
        "robustness": 0.4,
        "violated": False,
        "first_violation_t": None,
        "details": {"min_clearance_m": DEFAULT_CLEARANCE_M},
    }
    return OracleResult.model_validate(fields | overrides)


def make_run_outcome(**overrides: Any) -> RunOutcome:
    """Build a passing :class:`RunOutcome` with one satisfied oracle result."""
    fields: dict[str, Any] = {
        "verdict": Verdict.PASS,
        "robustness": 0.4,
        "primary_failure": None,
        "oracle_results": (make_oracle_result(),),
        "metrics": {"path_length_m": DEFAULT_PATH_LENGTH_M},
    }
    return RunOutcome.model_validate(fields | overrides)


def make_trace(
    *,
    n: int = DEFAULT_TRACE_SAMPLES,
    dt: float = DEFAULT_DT_S,
    speed: float = DEFAULT_SPEED_MPS,
    goal: tuple[float, float] | None = None,
    meta: dict[str, JsonValue] | None = None,
    **columns: npt.ArrayLike,
) -> Trace:
    """Build a synthetic straight-line run along +x that reaches its goal on the last sample.

    The robot drives at constant ``speed`` with perfect localisation, a constant
    :data:`DEFAULT_CLEARANCE_M` to the nearest obstacle and no contact; ``nav_status`` is ACTIVE
    and SUCCEEDED on the final sample. Override any column (e.g. ``min_obstacle_dist=[...]``) to
    craft oracle edge cases; values are cast to the column dtype and must have length ``n``.

    Args:
        n: Number of samples.
        dt: Sample period [s].
        speed: Forward speed [m/s].
        goal: Goal ``(x, y)`` [m]; defaults to the final position, so the run succeeds.
        meta: Trace metadata.
        **columns: Per-column overrides keyed by :class:`Trace` column name.

    Raises:
        TypeError: If an override names an unknown column.
        ValueError: If the resulting columns violate :class:`Trace` validation.
    """
    t = np.arange(n, dtype=np.float64) * dt
    x = speed * t
    nav_status = np.full(n, NavStatus.ACTIVE, dtype=np.int8)
    if n:
        nav_status[-1] = NavStatus.SUCCEEDED
    base: dict[str, npt.NDArray[Any]] = {
        "t": t,
        "gt_x": x,
        "gt_y": np.zeros(n),
        "gt_yaw": np.zeros(n),
        "est_x": x.copy(),
        "est_y": np.zeros(n),
        "est_yaw": np.zeros(n),
        "cmd_v": np.full(n, speed),
        "cmd_w": np.zeros(n),
        "meas_v": np.full(n, speed),
        "meas_w": np.zeros(n),
        "min_obstacle_dist": np.full(n, DEFAULT_CLEARANCE_M),
        "contact": np.zeros(n, dtype=np.bool_),
        "roll": np.zeros(n),
        "pitch": np.zeros(n),
        "nav_status": nav_status,
    }
    unknown = sorted(columns.keys() - base.keys())
    if unknown:
        msg = f"unknown Trace column override(s): {unknown}"
        raise TypeError(msg)
    for name, values in columns.items():
        base[name] = np.asarray(values, dtype=base[name].dtype)
    goal_x, goal_y = goal if goal is not None else (float(x[-1]) if n else 0.0, 0.0)
    return Trace(**base, goal_x=goal_x, goal_y=goal_y, meta=meta or {})
