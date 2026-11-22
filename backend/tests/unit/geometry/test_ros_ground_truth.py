"""Check that Gazebo and kinematic2d use the same clearance at the same poses."""

from __future__ import annotations

import importlib
from math import cos, sin
from pathlib import Path

import numpy as np
import numpy.testing as npt
import pytest
import yaml

from roboprobe.geometry import OccupancyGrid, PolygonFootprint, Rect, min_obstacle_distance
from roboprobe.scenario.map_io import load_ros_map, write_ros_map

pytestmark = pytest.mark.unit


def test_clearance_parity_with_gazebo_episode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use the same physical footprint, poses, and serialized map in both backends."""
    root = Path(__file__).resolve().parents[4]
    monkeypatch.syspath_prepend(str(root / "ros_ws/src/roboprobe_ros"))
    monitor_module = importlib.import_module("roboprobe_ros.ground_truth_monitor")
    occupied = np.zeros((20, 20), dtype=np.bool_)
    occupied[1, 2:16] = True
    occupied[4:16, 15] = True
    source = OccupancyGrid(occupied, 0.5, origin=(-2.5, -1.5))
    map_file = tmp_path / "warehouse.yaml"
    write_ros_map(map_file, source)

    vertices = [[-0.19, -0.17], [0.24, -0.17], [0.24, 0.17], [-0.19, 0.17]]
    pallet = Rect(x=3.25, y=0.5, yaw=0.25, length=1.2, width=0.8)
    episode = tmp_path / "episode.yaml"
    episode.write_text(
        yaml.safe_dump(
            {
                "map_file": map_file.name,
                "footprint": {"vertices_m": vertices},
                "pallets": [
                    {
                        "pose": {"x": pallet.x, "y": pallet.y, "yaw": pallet.yaw},
                        "size": [pallet.length, pallet.width, 0.135],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    poses = np.array([[1.0, 2.0, 0.4], [3.1, 0.8, -0.5], [5.5, 5.0, 0.0], [3.3, -3.0, 0.0]])
    expected = min_obstacle_distance(
        PolygonFootprint(np.array(vertices)), poses, load_ros_map(map_file), [pallet]
    )
    monitor = monitor_module.GroundTruthMonitor.from_episode(episode)
    observed = [
        monitor.evaluate((x, y), (0.0, 0.0, sin(yaw / 2), cos(yaw / 2))).clearance_m
        for x, y, yaw in poses
    ]
    npt.assert_allclose(observed, expected, rtol=0.0, atol=1e-13)
