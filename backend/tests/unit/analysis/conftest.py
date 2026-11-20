"""Helpers for failure-analysis unit tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from roboprobe.analysis.types import AnalysisRun
from roboprobe.core.types import FailureClass, Verdict
from roboprobe.scenario.space import ScenarioSpace

REPO_ROOT = Path(__file__).resolve().parents[4]
WAREHOUSE = REPO_ROOT / "configs" / "scenario_spaces" / "warehouse_v1.yaml"

DEFAULT_METRICS = {
    "s_fail": 2.0,
    "L_nominal": 10.0,
    "t_fail": 5.0,
    "T_max": 20.0,
    "min_clearance": 0.25,
    "max_loc_error": 0.1,
}


@pytest.fixture
def space() -> ScenarioSpace:
    return ScenarioSpace.from_yaml(WAREHOUSE, base_dir=REPO_ROOT)


def make_run(**overrides: Any) -> AnalysisRun:
    fields: dict[str, Any] = {
        "id": uuid4(),
        "verdict": Verdict.FAIL,
        "phase": "falsify",
        "primary_failure": FailureClass.COL,
        "values": {
            "robot.max_speed": 0.4,
            "obstacle.clearance": 0.2,
            "env.illuminance": 20.0,
            "sensor.lidar_noise_std": 0.08,
            "env.floor_friction": 0.8,
            "comms.cmd_delay_ms": 20.0,
            "obstacle.along_path": 0.5,
            "sensor.lidar_dropout": 0.0,
        },
        "metrics": dict(DEFAULT_METRICS),
    }
    return AnalysisRun.model_validate(fields | overrides)


def uid(n: int) -> UUID:
    return UUID(int=n)
