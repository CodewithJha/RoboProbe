from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest
from tests.factories import make_trace

from roboprobe.core.settings import OracleThresholds
from roboprobe.core.types import NavStatus, TaskSpec, Trace
from roboprobe.oracles import create_all

DT = 0.1  # 10 Hz (FR-RUN-004)


@pytest.fixture
def thresholds() -> OracleThresholds:
    return OracleThresholds()


@pytest.fixture
def task() -> TaskSpec:
    return make_task()


def make_task(**overrides: Any) -> TaskSpec:
    data: dict[str, Any] = {
        "schema_version": 1,
        "id": "oracle_fixture_v1",
        "world": {"kinematic2d": "worlds/k2d.json"},
        "map": "maps/k.yaml",
        "start": {"x": 0.0, "y": 0.0, "yaw": 0.0},
        "goal": {"x": 5.0, "y": 0.0, "yaw": 0.0},
        "goal_tolerance": {"xy": 0.25, "yaw": 0.5},
        "nominal_path": "paths/line.csv",
        "time_limit": {"factor": 100.0, "offset_s": 0.0, "cap_s": 20.0},
    }
    return TaskSpec.model_validate(data | overrides)


def long_trace(**columns: Any) -> Trace:
    """≥ 5 s at 10 Hz so InfraCheck duration passes with default T_max."""
    n = 51
    t = np.arange(n, dtype=np.float64) * DT
    x = np.linspace(0.0, 5.0, n)
    nav = np.full(n, NavStatus.ACTIVE, dtype=np.int8)
    nav[-1] = NavStatus.SUCCEEDED
    base: dict[str, Any] = {
        "n": n,
        "dt": DT,
        "speed": 0.0,
        "goal": (5.0, 0.0),
        "t": t,
        "gt_x": x,
        "est_x": x.copy(),
        "cmd_v": np.full(n, 0.5),
        "meas_v": np.full(n, 0.5),
        "min_obstacle_dist": np.full(n, 1.0),
        "nav_status": nav,
    }
    base.update(columns)
    return make_trace(**base)


@dataclass(frozen=True, slots=True)
class FakeEpisode:
    trace: Trace
    infra_error: str | None = None


@pytest.fixture
def oracles(thresholds: OracleThresholds):
    return create_all(thresholds)
