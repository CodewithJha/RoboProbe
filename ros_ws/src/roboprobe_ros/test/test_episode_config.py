"""Verify the materialized episode configuration and installed exit codes."""

# ruff: noqa: S101

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
import yaml
from roboprobe_ros.episode_config import (
    EpisodeConfig,
    EpisodeResult,
    EpisodeTime,
    episode_exit_codes,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def inputs() -> dict[str, object]:
    """Return the worker's episode YAML fields."""
    return {
        "start": {"x": 1.0, "y": 2.0, "yaw": -0.3},
        "goal": {"x": 4.5, "y": 6.0, "yaw": 0.5},
        "time_limit_s": 3.0,
        "wall_timeout_factor": 4.0,
        "startup_timeout_s": 2.0,
        "spawn_tolerance_m": 0.15,
    }


def test_reads_episode_limits(tmp_path: Path, inputs: dict[str, object]) -> None:
    """Convert the materialized factor to a wall-clock budget."""
    path = tmp_path / "episode.yaml"
    path.write_text(yaml.safe_dump(inputs), encoding="utf-8")
    assert EpisodeConfig.read(path) == EpisodeConfig(
        (1.0, 2.0, -0.3), (4.5, 6.0, 0.5), 3, 12, 2, 0.15
    )


@pytest.mark.parametrize(
    ("key", "value", "error"),
    [
        ("start", [0, 0, 0], TypeError),
        ("startup_timeout_s", 0, ValueError),
        ("wall_timeout_factor", float("inf"), ValueError),
        ("time_limit_s", False, ValueError),
    ],
)
def test_rejects_invalid_inputs(
    tmp_path: Path, inputs: dict[str, object], key: str, value: object, error: type[Exception]
) -> None:
    """Reject malformed poses, nonnumeric values, and invalid limits before starting ROS."""
    path = tmp_path / "episode.yaml"
    inputs[key] = value
    path.write_text(yaml.safe_dump(inputs), encoding="utf-8")
    with pytest.raises(error):
        EpisodeConfig.read(path)


def test_exit_codes_are_packaged() -> None:
    """Keep process outcomes stable for the worker reading the same YAML."""
    assert episode_exit_codes() == {
        "completed": 0,
        "startup_timeout": 10,
        "spawn_failed": 11,
        "internal_error": 12,
    }


def test_writes_worker_result(tmp_path: Path) -> None:
    """Publish one complete document with elapsed times across clock origins."""
    result = tmp_path / "episode_done.json"
    start = EpisodeTime(10.0, 20.0, "2026-11-22T20:00:00+00:00")
    end = EpisodeTime(12.0, 21.0, "2026-11-22T20:00:01+00:00")
    EpisodeResult("TIMEOUT", None, start, end, 2).write(result)
    assert json.loads(result.read_text(encoding="utf-8")) == {
        "status": "TIMEOUT",
        "nav_result_code": None,
        "t_start": start.utc,
        "t_end": end.utc,
        "sim_time_s": 2.0,
        "wall_time_s": 1.0,
        "rtf_mean": 2.0,
        "recoveries": 2,
    }
    assert not result.with_suffix(".tmp").exists()
