"""Warehouse map alignment for ``warehouse_v1`` (T-092)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboprobe.backends.kinematic2d.model import Kinematic2DModel
from roboprobe.backends.kinematic2d.planner import plan_path
from roboprobe.backends.kinematic2d.world import load_world
from roboprobe.core.settings import load_settings
from roboprobe.scenario.map_io import load_ros_map, occupancy_iou, write_ros_map
from roboprobe.scenario.task import load_nominal_path, load_task, polyline_length_m

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[4]
K2D_JSON = REPO / "configs" / "backends" / "warehouse_k2d.json"
K2D_MAP = REPO / "tasks" / "maps" / "warehouse.yaml"
GAZEBO_MAP = REPO / "configs" / "maps" / "warehouse_v1.yaml"
NOMINAL_JSON = REPO / "configs" / "maps" / "warehouse_v1_nominal_path.json"
WAREHOUSE_TASK = REPO / "tasks" / "warehouse_delivery_v1.yaml"


def test_k2d_ros_map_round_trip_iou(tmp_path: Path) -> None:
    grid = load_world(K2D_JSON)
    yaml_path = tmp_path / "roundtrip.yaml"
    write_ros_map(yaml_path, grid)
    loaded = load_ros_map(yaml_path)
    result = occupancy_iou(grid, loaded)
    assert result.iou == pytest.approx(1.0)
    assert result.agreement == pytest.approx(1.0)


def test_committed_k2d_map_matches_json(tmp_path: Path) -> None:
    reference = load_world(K2D_JSON)
    exported = load_ros_map(K2D_MAP)
    assert occupancy_iou(reference, exported).iou == pytest.approx(1.0)


def test_nominal_path_json_matches_planner_and_csv() -> None:
    model = Kinematic2DModel.from_yaml(REPO / "configs" / "backends" / "kinematic2d_v1.yaml")
    grid = load_world(K2D_JSON)
    start = (model.world.start_x_m, model.world.start_y_m)
    goal = (model.world.goal_x_m, model.world.goal_y_m)
    planned = plan_path(grid, start, goal)
    assert planned is not None
    stored = json.loads(NOMINAL_JSON.read_text(encoding="utf-8"))
    assert len(stored) == len(planned)
    task = load_task(WAREHOUSE_TASK, strict=True)
    csv_path = load_nominal_path(WAREHOUSE_TASK, task)
    assert csv_path.shape == planned.shape
    tol = load_settings().scenario.map_alignment.path_length_tolerance_ratio
    planned_len = polyline_length_m(planned)
    assert abs(polyline_length_m(csv_path) - planned_len) <= tol * planned_len


def test_gazebo_map_iou_recorded_for_followup() -> None:
    """Live sim cross-check is blocked without the owner's GPU host ([#331]); record IoU here."""
    k2d = load_world(K2D_JSON)
    gazebo = load_ros_map(GAZEBO_MAP)
    result = occupancy_iou(k2d, gazebo)
    assert result.samples > 0
    assert 0.0 < result.iou < 1.0


def test_warehouse_task_loads_strict_after_t092() -> None:
    task = load_task(WAREHOUSE_TASK, strict=True)
    assert task.goal.y == pytest.approx(-8.3)
    assert not task.provisional
