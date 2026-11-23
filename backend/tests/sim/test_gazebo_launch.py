"""Smoke one materialised warehouse episode using the installed Jazzy launch."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from tests.contract.test_backend_contract import _request

from roboprobe.backends.gazebo_nav2.backend import GazeboNav2Backend
from roboprobe.backends.gazebo_nav2.process import _orphan_pids
from roboprobe.backends.trace_io import read_trace, validate_trace
from roboprobe.core.settings import load_settings

pytestmark = pytest.mark.sim
_INPUTS = (
    "bridge.yaml",
    "episode.yaml",
    "map.pgm",
    "map.yaml",
    "nav2_params.yaml",
    "perception_model.yaml",
    "perturb_params.yaml",
    "topics.yaml",
    "world.sdf",
)
_TERMINAL_RESULTS = {"SUCCEEDED", "ABORTED", "CANCELED", "TIMEOUT"}
_MIN_TRACE_RATE_HZ = 19.0
_MAX_TRACE_GAP_S = 0.2


def test_materialised_episode_flushes_and_stops(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    """Start the real simulator and verify a fresh nonempty Trace v1 and terminal result."""
    fixture = os.environ.get("ROBOPROBE_GAZEBO_LAUNCH_WORKDIR")
    if fixture is not None:
        for name in _INPUTS:
            shutil.copyfile(Path(fixture) / name, tmp_path / name)
    elif request.config.getoption("--backend") == "gazebo_nav2":
        settings = load_settings()
        episode = _request(tmp_path, settings, backend_name="gazebo_nav2")
        GazeboNav2Backend(settings).materialize(episode)
    else:
        pytest.skip("Select --backend gazebo_nav2 or set ROBOPROBE_GAZEBO_LAUNCH_WORKDIR.")

    cfg = yaml.safe_load((tmp_path / "episode.yaml").read_text(encoding="utf-8"))
    timeout = cfg["startup_timeout_s"] + cfg["time_limit_s"] * cfg["wall_timeout_factor"]
    timeout += 2 * cfg["teardown_grace_s"]
    ros2 = shutil.which("ros2")
    assert ros2 is not None, "Source the installed Jazzy environment before running the smoke test."
    partition = f"rp_launch_smoke_{uuid4().hex}"
    result = subprocess.run(  # noqa: S603 - uses the installed ROS launch entry point directly.
        [ros2, "launch", "roboprobe_ros", "episode.launch.py", f"workdir:={tmp_path}"],
        env={**os.environ, "GZ_PARTITION": partition},
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    (tmp_path / "episode.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == 0, result.stdout[-5000:] + result.stderr[-5000:]
    assert not _orphan_pids(partition), "ROS launch left simulator processes in its partition."
    state = json.loads((tmp_path / "episode_done.json").read_text(encoding="utf-8"))
    assert state["status"] in _TERMINAL_RESULTS
    trace = read_trace(tmp_path / "trace.parquet")
    assert not validate_trace(trace, min_hz=_MIN_TRACE_RATE_HZ, max_gap_s=_MAX_TRACE_GAP_S)
