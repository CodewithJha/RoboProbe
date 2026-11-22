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
from roboprobe.scenario.task import load_nominal_path

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]


def _settings() -> RoboProbeSettings:
    return RoboProbeSettings(
        backends={
            "kinematic2d": {
                "model_file": str(REPO / "configs/backends/kinematic2d_v1.yaml"),
                "perception_model_file": str(REPO / "configs/perception/oakd_k2d_v1.yaml"),
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
        task=space.task,
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
    world_source = REPO / a.task.world["kinematic2d"]
    assert ma.files["world"].read_bytes() == world_source.read_bytes()
    task_file = REPO / "tasks/warehouse_delivery_aligned_v1.yaml"
    assert ma.payload["nominal_path"] == load_nominal_path(task_file, a.task).tolist()


def test_run_episode_writes_trace(tmp_path: Path) -> None:
    settings = _settings()
    backend = Kinematic2DBackend(settings)
    req = _request(tmp_path, settings)
    materialized = backend.materialize(req)
    result = backend.run_episode(req, materialized)
    assert result.infra_error is None
    assert result.artifacts["trace"].is_file()
    assert result.backend_meta["k2d_model_version"] == "kinematic2d_v1"


def test_legacy_task_uses_the_calibrated_world_model(tmp_path: Path) -> None:
    settings = _settings()
    backend = Kinematic2DBackend(settings)
    req = _request(tmp_path, settings)
    task = req.task.model_copy(update={"world": {"kinematic2d": "worlds/warehouse_k2d.json"}})
    materialized = backend.materialize(req.model_copy(update={"task": task}))
    expected = REPO / "configs/backends/warehouse_k2d.json"
    assert materialized.files["world"].read_bytes() == expected.read_bytes()
    assert "nominal_path" not in materialized.payload
