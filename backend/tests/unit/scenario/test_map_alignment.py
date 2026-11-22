"""Warehouse map alignment for ``warehouse_v1`` (T-092)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from roboprobe.backends.kinematic2d.world import load_world
from roboprobe.core.settings import load_settings
from roboprobe.scenario.map_io import load_ros_map, occupancy_iou, write_ros_map
from roboprobe.scenario.task import load_nominal_path, load_task, polyline_length_m

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[4]
K2D_JSON = REPO / "configs" / "backends" / "warehouse_k2d.json"
K2D_MAP = REPO / "tasks" / "maps" / "warehouse.yaml"
ALIGNED_JSON = REPO / "configs" / "maps" / "warehouse_v1_k2d.json"
GAZEBO_MAP = REPO / "configs" / "maps" / "warehouse_v1.yaml"
NOMINAL_JSON = REPO / "configs" / "maps" / "warehouse_v1_nominal_path.json"
WAREHOUSE_TASK = REPO / "tasks" / "warehouse_delivery_aligned_v1.yaml"


def test_k2d_ros_map_round_trip_iou(tmp_path: Path) -> None:
    grid = load_world(K2D_JSON)
    yaml_path = tmp_path / "roundtrip.yaml"
    write_ros_map(yaml_path, grid)
    loaded = load_ros_map(yaml_path)
    result = occupancy_iou(grid, loaded)
    assert result.iou == pytest.approx(1.0)
    assert result.agreement == pytest.approx(1.0)


def test_committed_legacy_k2d_map_matches_json() -> None:
    reference = load_world(K2D_JSON)
    exported = load_ros_map(K2D_MAP)
    assert occupancy_iou(reference, exported).iou == pytest.approx(1.0)


def test_ros_map_uses_black_occupied_and_bottom_left_world_origin(tmp_path: Path) -> None:
    image = tmp_path / "asymmetric.pgm"
    image.write_bytes(b"P5\n3 2\n255\n" + bytes([0, 255, 205, 255, 255, 0]))
    metadata = tmp_path / "map.yaml"
    metadata.write_text(
        "image: asymmetric.pgm\nmode: trinary\nresolution: 0.5\n"
        "origin: [1, 2, 0]\nnegate: 0\nfree_thresh: 0.1\noccupied_thresh: 0.65\n",
        encoding="utf-8",
    )
    grid = load_ros_map(metadata)
    assert grid.origin == (1, 2)
    np.testing.assert_array_equal(grid.occupied, [[False, False, True], [True, False, True]])


def test_nominal_path_csv_matches_actual_nav2_planner_output() -> None:
    planned = np.asarray(json.loads(NOMINAL_JSON.read_text(encoding="utf-8")))
    task = load_task(WAREHOUSE_TASK, strict=True)
    csv_path = load_nominal_path(WAREHOUSE_TASK, task)
    np.testing.assert_allclose(csv_path, planned)
    settings = load_settings()
    tol = settings.scenario.map_alignment.path_length_tolerance_ratio
    planned_len = polyline_length_m(planned)
    assert planned_len == pytest.approx(13.01)
    assert abs(polyline_length_m(csv_path) - planned_len) <= tol * planned_len
    gazebo = load_ros_map(GAZEBO_MAP)
    assert float(np.min(gazebo.distance_at(planned))) > settings.oracles.clear.d_safe


def test_aligned_kinematic_map_matches_gazebo() -> None:
    k2d = load_world(ALIGNED_JSON)
    gazebo = load_ros_map(GAZEBO_MAP)
    offset = np.abs(np.asarray(k2d.origin) - np.asarray(gazebo.origin)) / gazebo.resolution
    result = occupancy_iou(k2d, gazebo)
    assert max(offset) <= 1
    assert result.iou >= load_settings().scenario.map_alignment.min_iou


def test_warehouse_task_loads_strict_after_t092() -> None:
    task = load_task(WAREHOUSE_TASK, strict=True)
    assert task.goal.y == pytest.approx(-8.3)
    assert not task.provisional
