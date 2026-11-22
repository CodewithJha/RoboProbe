"""Read the episode inputs and exit codes shared by the worker and ROS manager."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path

import yaml
from ament_index_python.packages import get_package_share_directory


def episode_exit_codes() -> dict[str, int]:
    """Return the process exit classifications distributed with the ROS topic map."""
    share = Path(get_package_share_directory("roboprobe_ros"))
    with (share / "config" / "episode_exit_codes.yaml").open(encoding="utf-8") as config:
        return {str(key): int(code) for key, code in yaml.safe_load(config).items()}


def _float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        msg = "Episode poses, time limits and tolerance must be finite numbers"
        raise ValueError(msg)
    return float(value)


def _pose(data: object) -> tuple[float, float, float]:
    if not isinstance(data, dict):
        msg = "Episode start and goal must specify x, y and yaw"
        raise TypeError(msg)
    return _float(data["x"]), _float(data["y"]), _float(data["yaw"])


@dataclass(frozen=True)
class EpisodeConfig:
    """Start, goal and timing limits materialized for one navigation episode."""

    start: tuple[float, float, float]
    goal: tuple[float, float, float]
    sim_limit: float
    wall_limit: float
    startup_limit: float
    spawn_tolerance: float

    @classmethod
    def read(cls, path: Path) -> EpisodeConfig:
        """Read finite poses and positive limits from the worker's episode YAML."""
        with path.open(encoding="utf-8") as stream:
            data = yaml.safe_load(stream)
        sim_limit = _float(data["time_limit_s"])
        limits = (
            sim_limit,
            _float(data["wall_timeout_factor"]) * sim_limit,
            _float(data["startup_timeout_s"]),
            _float(data["spawn_tolerance_m"]),
        )
        if not isfinite(limits[1]) or min(limits) <= 0.0:
            msg = "Episode time limits and spawn tolerance must be finite and positive"
            raise ValueError(msg)
        return cls(_pose(data["start"]), _pose(data["goal"]), *limits)
