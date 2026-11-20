"""Warehouse occupancy clone (T-032)."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from roboprobe.backends.kinematic2d.model import Kinematic2DModel
from roboprobe.backends.kinematic2d.world import (
    dump_world_json,
    load_world,
    nominal_path_polyline,
)
from roboprobe.scenario.task import polyline_length_m

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]
MODEL = Kinematic2DModel.from_yaml(REPO / "configs" / "backends" / "kinematic2d_v1.yaml")
WORLD_JSON = REPO / "configs" / "backends" / "warehouse_k2d.json"
LOAD_BUDGET_S = 0.05
PATH_MIN_M, PATH_MAX_M = 12.0, 15.0


def test_committed_json_matches_generator() -> None:
    assert WORLD_JSON.read_text(encoding="utf-8") == dump_world_json(MODEL)


def test_dump_is_byte_identical() -> None:
    assert dump_world_json(MODEL) == dump_world_json(MODEL)


def test_world_loads_within_budget() -> None:
    t0 = time.perf_counter()
    grid = load_world(WORLD_JSON)
    elapsed = time.perf_counter() - t0
    assert elapsed < LOAD_BUDGET_S
    assert grid.resolution == MODEL.world.resolution_m
    cell = grid.world_to_cell(np.array([MODEL.world.start_x_m, MODEL.world.start_y_m]))
    assert not grid.occupied[int(cell[0]), int(cell[1])]


def test_nominal_path_length() -> None:
    path = nominal_path_polyline(MODEL.world)
    length = polyline_length_m(path)
    assert PATH_MIN_M <= length <= PATH_MAX_M
    np.testing.assert_allclose(path[0], [MODEL.world.start_x_m, MODEL.world.start_y_m])
    np.testing.assert_allclose(path[-1], [MODEL.world.goal_x_m, MODEL.world.goal_y_m])
