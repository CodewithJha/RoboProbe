"""Kinematic2DBackend adapter (T-035b)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from roboprobe.backends.base import EpisodeRequest, episode_timeouts
from roboprobe.backends.kinematic2d.backend import Kinematic2DBackend
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import SutProfile
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.task import load_task

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]


def _settings() -> RoboProbeSettings:
    return RoboProbeSettings(
        backends={
            "kinematic2d": {
                "model_file": str(REPO / "configs" / "backends" / "kinematic2d_v1.yaml")
            },
            "gazebo_nav2": {
                "perception_model_file": str(
                    REPO / "configs" / "perception" / "oakd_lowlight_v1.yaml"
                )
            },
        }
    )


def _request(tmp_path: Path, settings: RoboProbeSettings) -> EpisodeRequest:
    space = ScenarioSpace.from_yaml(
        REPO / "configs" / "scenario_spaces" / "warehouse_v1.yaml", base_dir=REPO
    )
    sim, wall = episode_timeouts(settings.worker)
    return EpisodeRequest(
        run_id=uuid4(),
        scenario=space.nominal(),
        task=load_task(REPO / "tasks" / "warehouse_delivery_v1.yaml", strict=False),
        sut_profile=SutProfile(id="k2d", backend="kinematic2d", config={}, config_hash="a" * 16),
        seed=11,
        workdir=tmp_path / "run",
        sim_time_budget_s=sim,
        wall_timeout_s=wall,
    )


def test_materialize_is_byte_identical(tmp_path: Path) -> None:
    settings = _settings()
    backend = Kinematic2DBackend(settings)
    a = _request(tmp_path / "a", settings)
    b = _request(tmp_path / "b", settings)
    ma, mb = backend.materialize(a), backend.materialize(b)
    assert ma.files["world"].read_bytes() == mb.files["world"].read_bytes()
    assert ma.files["obstacle"].read_bytes() == mb.files["obstacle"].read_bytes()


def test_run_episode_writes_trace(tmp_path: Path) -> None:
    settings = _settings()
    backend = Kinematic2DBackend(settings)
    req = _request(tmp_path, settings)
    materialized = backend.materialize(req)
    result = backend.run_episode(req, materialized)
    assert result.infra_error is None
    assert result.artifacts["trace"].is_file()
    assert result.backend_meta["k2d_model_version"] == "kinematic2d_v1"
