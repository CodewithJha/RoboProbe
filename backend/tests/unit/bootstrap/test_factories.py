"""Composition-root factories (T-046)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from roboprobe.backends.base import PLUGIN_API_VERSION, BackendCapabilities
from roboprobe.backends.registry import ENTRY_POINT_GROUP
from roboprobe.bootstrap import build_cli_services, build_orchestrator, build_worker
from roboprobe.bootstrap.api import build_api
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.runner.worker import WorkerProcess
from roboprobe.scenario.task import load_task

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[4]


class FakeBackend:
    """Minimal backend plugin used only in the swap test."""

    PLUGIN_API_VERSION = PLUGIN_API_VERSION

    def __init__(self, settings: RoboProbeSettings) -> None:
        """Retain settings for the registry contract."""
        self.settings = settings
        self.capabilities = BackendCapabilities(
            name="fake",
            supported_params=frozenset({"robot.max_speed"}),
            deterministic=True,
            typical_episode_wall_s=1.0,
            max_parallel_per_host=1,
        )

    def prepare(self) -> None:
        return None

    def materialize(self, request: object) -> object:
        del request
        return SimpleNamespace(files={}, payload={})

    def run_episode(self, request: object, materialized: object, on_progress: object) -> object:
        del request, materialized, on_progress
        msg = "fake backend does not run episodes"
        raise NotImplementedError(msg)

    def cancel(self) -> None:
        return None

    def shutdown(self) -> None:
        return None


def _settings(tmp_path: Path, *, backend: str = "kinematic2d") -> RoboProbeSettings:
    return RoboProbeSettings(
        storage={"workdir_root": str(tmp_path / "w"), "artifact_root": str(tmp_path / "a")},
        worker={"backend": backend, "id_prefix": "test"},
        backends={
            "kinematic2d": {
                "model_file": str(REPO / "configs" / "backends" / "kinematic2d_v1.yaml")
            },
            "gazebo_nav2": {
                "perception_model_file": str(
                    REPO / "configs" / "perception" / "oakd_lowlight_v1.yaml"
                )
            },
        },
        observability={"metrics_enabled": False},
    )


def test_build_worker_uses_backend_from_settings(tmp_path: Path) -> None:
    task = load_task(REPO / "tasks" / "warehouse_delivery_v1.yaml", strict=False)
    worker = build_worker(_settings(tmp_path), task=task)
    assert isinstance(worker, WorkerProcess)
    assert worker.backend.capabilities.name == "kinematic2d"


def test_swapping_backend_name_switches_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ep = SimpleNamespace(name="fake", load=lambda: FakeBackend)
    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group=None: [ep] if group == ENTRY_POINT_GROUP else [],
    )
    task = load_task(REPO / "tasks" / "warehouse_delivery_v1.yaml", strict=False)
    worker = build_worker(_settings(tmp_path, backend="fake"), task=task)
    assert isinstance(worker.backend, FakeBackend)


def test_build_cli_and_orchestrator(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    cli = build_cli_services(settings)
    orch = build_orchestrator(settings)
    try:
        assert cli.settings is settings
        assert orch.settings is settings
        assert orch.scheduler is not None
        assert orch.reaper is not None
    finally:
        cli.close()
        orch.close()


def test_build_api_wires_infra(tmp_path: Path) -> None:
    services = build_api(_settings(tmp_path))
    try:
        assert services.settings is not None
        assert "backends" in services.plugin_catalog
        assert "strategies" in services.plugin_catalog
    finally:
        services.close()
