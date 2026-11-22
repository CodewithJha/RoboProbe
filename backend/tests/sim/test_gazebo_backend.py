"""Real Gazebo lifecycle checks (T-096b, FR-SIM-003)."""

from __future__ import annotations

import shutil
from pathlib import Path

import psutil
import pytest
from tests.contract.test_backend_contract import _request

from roboprobe.backends.gazebo_nav2.backend import GazeboNav2Backend, InfraReason
from roboprobe.core.settings import load_settings
from roboprobe.scenario.sut_profile import config_hash

pytestmark = pytest.mark.sim


@pytest.mark.timeout(420)
def test_simulator_loss_during_navigation_is_infrastructure_failure(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    if request.config.getoption("--backend") != "gazebo_nav2" or shutil.which("ros2") is None:
        pytest.skip("requires a sourced Jazzy worker image and --backend gazebo_nav2")

    settings = load_settings()
    settings = settings.model_copy(
        update={"worker": settings.worker.model_copy(update={"poll_interval_s": 0.1})}
    )
    backend = GazeboNav2Backend(settings)
    backend.prepare()
    episode = _request(tmp_path, settings, backend_name="gazebo_nav2")
    # Give the test enough time to interrupt the live controller on a shared CI host.
    profile = episode.sut_profile
    config = {
        **profile.config,
        "nav2_overrides": {"bt_navigator": {"ros__parameters": {"default_server_timeout": 1000}}},
    }
    episode = episode.model_copy(
        update={
            "sut_profile": profile.model_copy(
                update={"config": config, "config_hash": config_hash(profile.backend, config)}
            )
        }
    )
    generated = backend.materialize(episode)
    log = episode.workdir / "episode.log"
    killed = False

    def kill_gazebo(_: float) -> None:
        nonlocal killed
        if killed or "Received a goal, begin computing control effort" not in log.read_text(
            encoding="utf-8", errors="replace"
        ):
            return
        for process in psutil.process_iter(["name", "cmdline"]):
            try:
                name = process.info["name"] or ""
                arguments = process.info["cmdline"] or []
                command = " ".join(arguments).split(maxsplit=2)
                server = name.startswith("gz sim server") or (
                    len(command) >= 2 and Path(command[0]).name == "gz" and command[1] == "sim"
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
