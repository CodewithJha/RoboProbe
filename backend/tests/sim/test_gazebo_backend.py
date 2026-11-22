"""Real Gazebo lifecycle checks (T-096b, FR-SIM-003)."""

from __future__ import annotations

import shutil
from pathlib import Path

import psutil
import pytest
from tests.contract.test_backend_contract import _request

from roboprobe.backends.gazebo_nav2.backend import GazeboNav2Backend, InfraReason
from roboprobe.core.settings import load_settings

pytestmark = pytest.mark.sim


@pytest.mark.timeout(420)
def test_simulator_loss_during_navigation_is_infrastructure_failure(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    if request.config.getoption("--backend") != "gazebo_nav2" or shutil.which("ros2") is None:
        pytest.skip("requires a sourced Jazzy worker image and --backend gazebo_nav2")

    settings = load_settings()
    backend = GazeboNav2Backend(settings)
    backend.prepare()
    episode = _request(tmp_path, settings, backend_name="gazebo_nav2")
    generated = backend.materialize(episode)
    log = episode.workdir / "episode.log"
    killed = False

    def kill_gazebo(_: float) -> None:
        nonlocal killed
        if killed or "Begin navigating from current location" not in log.read_text(
            encoding="utf-8", errors="replace"
        ):
            return
        for process in psutil.process_iter(["name", "cmdline"]):
            try:
                name = process.info["name"] or ""
                arguments = process.info["cmdline"] or []
                server = name.startswith("gz sim server") or any(
                    argument.startswith("gz sim server") for argument in arguments
                )
                if server and process.environ().get("GZ_PARTITION", "").endswith(
                    episode.run_id.hex
                ):
                    process.kill()
                    killed = True
                    return
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    result = backend.run_episode(episode, generated, on_progress=kill_gazebo)
    assert killed, log.read_text(encoding="utf-8", errors="replace")
    assert result.infra_error in {
        InfraReason.LAUNCH_FAILED,
        InfraReason.INTERNAL_ERROR,
        InfraReason.RESULT_INVALID,
    }
    backend.shutdown()
