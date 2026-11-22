"""Shared ground-truth measurements for Gazebo episode traces (T-094a)."""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, atan2, hypot, isfinite
from typing import TYPE_CHECKING, Self

import numpy as np
import yaml

from roboprobe_ros._vendor.geometry import CircleFootprint, PolygonFootprint, Rect
from roboprobe_ros._vendor.geometry.distance import min_obstacle_distance
from roboprobe_ros._vendor.geometry.ros_map import decode_ros_pgm

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from roboprobe_ros._vendor.geometry import Footprint, OccupancyGrid

__all__ = ["GroundTruthMonitor", "GroundTruthSample"]


_VEC3 = 3


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        msg = f"{label} must be a mapping with string keys"
        raise ValueError(msg)
    return {str(key): item for key, item in value.items()}


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not isfinite(value):
        msg = f"{label} must be a finite number"
        raise ValueError(msg)
    return float(value)


def _sequence(value: object, label: str, size: int | None = None) -> list[object]:
    if not isinstance(value, list) or (size is not None and len(value) != size):
        msg = f"{label} must be a list with the expected dimensions"
        raise ValueError(msg)
    return list(value)


def _relative_file(parent: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        msg = f"{label} must identify a relative file"
        raise ValueError(msg)
    root = parent.resolve()
    filename = (root / value).resolve()
    if not filename.is_relative_to(root):
        msg = f"{label} must stay inside {root}"
        raise ValueError(msg)
    return filename


def _load_grid(path: Path) -> OccupancyGrid:
    metadata = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), "map")
    origin = _sequence(metadata.get("origin"), "map.origin", _VEC3)
    if origin[2] != 0.0:
        msg = "map.origin must have a yaw of zero"
        raise ValueError(msg)
    image = _relative_file(path.parent, metadata.get("image"), "map.image")
    return decode_ros_pgm(
        image.read_bytes(),
        resolution=_number(metadata.get("resolution"), "map.resolution"),
        origin=(_number(origin[0], "map.origin.x"), _number(origin[1], "map.origin.y")),
        free_thresh=_number(metadata.get("free_thresh"), "map.free_thresh"),
        negate=bool(metadata.get("negate", 0)),
    )


def _load_footprint(value: object) -> Footprint:
    shape = _mapping(value, "footprint")
    if "vertices_m" in shape:
        return PolygonFootprint(np.asarray(shape["vertices_m"], dtype=np.float64))
    return CircleFootprint(_number(shape.get("radius_m"), "footprint.radius_m"))


def _pallet(value: object) -> Rect:
    record = _mapping(value, "pallet")
    pose = _mapping(record.get("pose"), "pallet.pose")
    size = _sequence(record.get("size"), "pallet.size", _VEC3)
    return Rect(
        x=_number(pose.get("x"), "pallet.pose.x"),
        y=_number(pose.get("y"), "pallet.pose.y"),
        yaw=_number(pose.get("yaw"), "pallet.pose.yaw"),
        length=_number(size[0], "pallet.size.x"),
        width=_number(size[1], "pallet.size.y"),
    )


@dataclass(frozen=True, slots=True)
class GroundTruthSample:
    """Clearance in metres and prevailing orientation in radians."""

    clearance_m: float
    roll_rad: float
    pitch_rad: float
    yaw_rad: float


class GroundTruthMonitor:
    """Evaluate camera-independent geometry in the recorder's process."""

    def __init__(
        self, footprint: Footprint, grid: OccupancyGrid, pallets: Sequence[Rect] = ()
    ) -> None:
        """Reuse the precomputed map distance transform over an episode."""
        self._footprint = footprint
        self._grid = grid
        self._pallets = tuple(pallets)

    @classmethod
    def from_episode(cls, episode_file: Path) -> Self:
        """Build the monitor from the workspace map, footprint and pallet definitions."""
        episode = _mapping(yaml.safe_load(episode_file.read_text(encoding="utf-8")), "episode")
        map_file = _relative_file(episode_file.parent, episode.get("map_file"), "episode.map_file")
        pallets = _sequence(episode.get("pallets", []), "episode.pallets")
        return cls(
            _load_footprint(episode.get("footprint")),
            _load_grid(map_file),
            [_pallet(pallet) for pallet in pallets],
        )

    def evaluate(
        self, position: tuple[float, float], quaternion: tuple[float, float, float, float]
    ) -> GroundTruthSample:
        """Measure a planar pose using the ROS quaternion in x, y, z, w order."""
        scale = hypot(*quaternion)
        if not isfinite(scale) or scale == 0.0:
            msg = "ground-truth quaternion must be finite and nonzero"
            raise ValueError(msg)
        x, y, z, w = (value / scale for value in quaternion)
        roll = atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
        pitch = asin(max(-1.0, min(1.0, 2.0 * (w * y - z * x))))
        yaw = atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
        clearance = min_obstacle_distance(
            self._footprint, [(*position, yaw)], self._grid, self._pallets
        )
        return GroundTruthSample(float(clearance[0]), roll, pitch, yaw)
