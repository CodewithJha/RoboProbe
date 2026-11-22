"""Gazebo worker result protocol and launch configuration (T-096b)."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from tests.factories import make_trace

from roboprobe.backends.base import EpisodeRequest, MaterializedScenario
from roboprobe.backends.gazebo_nav2.backend import GazeboNav2Backend, InfraReason
from roboprobe.backends.gazebo_nav2.process import EpisodeProcess, ProcessExit, ProcessState
from roboprobe.backends.trace_io import write_trace
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import NavStatus
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.sut_profile import load_sut_profile

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[5]
SUMMARY = {"sim_time_s": 20, "wall_time_s": 25, "rtf_mean": 0.8, "recoveries": 1}


@pytest.fixture
def episode_request(tmp_path: Path) -> EpisodeRequest:
    space = ScenarioSpace.from_yaml(
        ROOT / "configs/scenario_spaces/warehouse_v1.yaml", base_dir=ROOT
    )
    sut = load_sut_profile(ROOT / "configs/sut_profiles/tb4_nav2_default.yaml", strict=True)
    return EpisodeRequest(
        run_id=uuid4(),
        scenario=space.nominal(),
        task=space.task,
        sut_profile=sut,
        seed=1,
        workdir=tmp_path,
        sim_time_budget_s=30,
        wall_timeout_s=90,
    )


def test_completed_launch_uses_terminal_file_and_trace(
    monkeypatch: pytest.MonkeyPatch, episode_request: EpisodeRequest
) -> None:
    def run_process(_self, command, *, workdir, env, wall_timeout_s, **_):
        assert workdir == episode_request.workdir.resolve()
        assert command == [
            "ros2",
            "launch",
            "roboprobe_ros",
            "episode.launch.py",
            f"workdir:={workdir}",
        ]
        assert env["ROS_DOMAIN_ID"] == "30"
        assert env["GZ_PARTITION"].startswith("rp_") and env["GZ_PARTITION"].endswith("_0")
        assert env["ROS_AUTOMATIC_DISCOVERY_RANGE"] == "LOCALHOST"
        assert wall_timeout_s == 43
        assert not (workdir / "episode_done.json").exists()
        (workdir / "episode_done.json").write_text(
            json.dumps({"status": "TIMEOUT", **SUMMARY}), encoding="utf-8"
        )
        write_trace(make_trace(n=2, nav_status=[NavStatus.ACTIVE] * 2), workdir / "trace.parquet")
        return ProcessExit(ProcessState.EXITED, 0)

    monkeypatch.setattr(EpisodeProcess, "run", run_process)
    (episode_request.workdir / "episode_done.json").write_text("stale", encoding="utf-8")
    settings = RoboProbeSettings(
        storage={"workdir_root": episode_request.workdir},
        backends={"gazebo_nav2": {"startup_timeout_s": 20, "wall_margin_s": 3}},
    )
    result = GazeboNav2Backend(settings).run_episode(
        episode_request, MaterializedScenario(payload={"time_limit_s": 20})
    )
    assert result.infra_error is None
    assert result.backend_meta["status"] == "TIMEOUT"
    assert result.backend_meta["sim_time_s"] == "20.0"
    assert result.trace.n_samples > 1


@pytest.mark.parametrize(
    "case",
    [
        (ProcessState.EXITED, 10, None, InfraReason.STARTUP_TIMEOUT),
        (ProcessState.EXITED, 11, None, InfraReason.SPAWN_FAILED),
        (ProcessState.EXITED, 12, None, InfraReason.INTERNAL_ERROR),
        (ProcessState.EXITED, -9, None, InfraReason.LAUNCH_FAILED),
        (ProcessState.EXITED, 0, "STARTUP_TIMEOUT", InfraReason.STARTUP_TIMEOUT),
        (ProcessState.EXITED, 0, "SPAWN_FAILED", InfraReason.SPAWN_FAILED),
        (ProcessState.EXITED, 0, "INTERNAL_ERROR", InfraReason.INTERNAL_ERROR),
        (ProcessState.EXITED, 0, None, InfraReason.RESULT_INVALID),
        (ProcessState.EXITED, 0, "SUCCEEDED", InfraReason.TRACE_INVALID),
        (ProcessState.CANCELED, -2, None, InfraReason.CANCELED),
        (ProcessState.WALL_TIMEOUT, -9, None, InfraReason.WALL_TIMEOUT),
    ],
)
def test_infra_classifications(
    monkeypatch: pytest.MonkeyPatch,
    episode_request: EpisodeRequest,
    case: tuple[ProcessState, int, str | None, InfraReason],
) -> None:
    state, returncode, summary_status, expected = case

    def run_process(_self, *_args, **kw):
        if summary_status is not None:
            (kw["workdir"] / "episode_done.json").write_text(
                json.dumps({"status": summary_status, **SUMMARY}), encoding="utf-8"
            )
        return ProcessExit(state, returncode)

    monkeypatch.setattr(EpisodeProcess, "run", run_process)
    settings = RoboProbeSettings(storage={"workdir_root": episode_request.workdir})
    result = GazeboNav2Backend(settings).run_episode(
        episode_request, MaterializedScenario(payload={"time_limit_s": 20})
    )
    assert result.infra_error == expected
    assert result.trace.n_samples == 2


@pytest.mark.parametrize("bag", ["complete", "partial", "missing", "split", "symlink", "disabled"])
def test_bag_artifact_requires_current_finalized_mcap(
    monkeypatch: pytest.MonkeyPatch, episode_request: EpisodeRequest, bag: str
) -> None:
    magic = b"\x89MCAP0\r\n"
    directory = episode_request.workdir / "bag"
    directory.mkdir()
    (directory / "previous_attempt.mcap").write_bytes(magic + b"old" + magic)

    def run_process(_self, *_args, **kw):
        assert not directory.exists()
        (kw["workdir"] / "episode_done.json").write_text(
            json.dumps({"status": "TIMEOUT", **SUMMARY}), encoding="utf-8"
        )
        write_trace(
            make_trace(n=2, nav_status=[NavStatus.ACTIVE] * 2), kw["workdir"] / "trace.parquet"
        )
        if bag not in {"disabled", "missing"}:
            directory.mkdir()
            output = directory / "bag_0.mcap"
            if bag == "symlink":
                target = kw["workdir"] / "other.mcap"
                target.write_bytes(magic + b"not a recorder output" + magic)
                output.symlink_to(target)
            else:
                output.write_bytes(magic + b"body" + (b"" if bag == "partial" else magic))
            if bag == "split":
                (directory / "bag_1.mcap").write_bytes(magic + b"second" + magic)
        return ProcessExit(ProcessState.EXITED, 0)

    monkeypatch.setattr(EpisodeProcess, "run", run_process)
    result = GazeboNav2Backend(RoboProbeSettings()).run_episode(
        episode_request,
        MaterializedScenario(
            payload={"time_limit_s": 20, "record_bag": "never" if bag == "disabled" else "always"}
        ),
    )
    if bag == "complete":
        assert result.infra_error is None
        assert result.artifacts["bag"] == directory / "bag_0.mcap"
    else:
        assert "bag" not in result.artifacts
        assert result.infra_error == (None if bag == "disabled" else InfraReason.BAG_INVALID)
