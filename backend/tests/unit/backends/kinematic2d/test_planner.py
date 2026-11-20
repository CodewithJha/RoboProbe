"""A* planner (T-033c)."""

from __future__ import annotations

import numpy as np
import pytest

from roboprobe.backends.kinematic2d.planner import plan_path
from roboprobe.geometry import OccupancyGrid

pytestmark = pytest.mark.unit
RES = 0.1


def test_finds_path_on_open_grid() -> None:
    occupied = np.zeros((20, 20), dtype=bool)
    occupied[0, :] = occupied[-1, :] = occupied[:, 0] = occupied[:, -1] = True
    grid = OccupancyGrid(occupied, RES)
    path = plan_path(grid, (0.55, 0.55), (1.55, 0.55))
    assert path is not None
    assert len(path) >= 2


def test_returns_none_when_blocked() -> None:
    occupied = np.zeros((10, 10), dtype=bool)
    occupied[:, 5] = True
    grid = OccupancyGrid(occupied, RES)
    assert plan_path(grid, (0.25, 0.55), (0.85, 0.55)) is None
