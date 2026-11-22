"""Rolling costmap (T-033b)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from roboprobe.backends.kinematic2d.costmap import RollingCostmap, overlay_sensor_hits
from roboprobe.backends.kinematic2d.model import Kinematic2DModel
from roboprobe.backends.kinematic2d.sensors import Lidar
from roboprobe.core.seeding import SENSOR, make_rng
from roboprobe.core.settings.backends import Kinematic2DSettings
from roboprobe.geometry import GridRayCaster, OccupancyGrid

pytestmark = pytest.mark.unit

MODEL = Kinematic2DModel.from_yaml(
    Path(__file__).resolve().parents[5] / "configs" / "backends" / "kinematic2d_v1.yaml"
)


def empty_room() -> OccupancyGrid:
    occupied = np.zeros((80, 80), dtype=bool)
    occupied[0, :] = occupied[-1, :] = occupied[:, 0] = occupied[:, -1] = True
    return OccupancyGrid(occupied, 0.05)


def test_sensor_overlay_keeps_static_cells_and_inflates_valid_hits_at_edges() -> None:
    base = np.zeros((6, 6), dtype=bool)
    base[5, 5] = True
    grid = OccupancyGrid(base, 1.0)
    overlay = overlay_sensor_hits(
        grid,
        (0.5, 0.5, 0.0),
        np.array([0.4, 7, np.inf]),
        np.array([0, 0, 0]),
        np.array([3.0]),
        np.array([0.0]),
        lidar_inflation_cells=1,
    )
    expected = base.copy()
    expected[:2, :2] = True
    expected[0, 3] = True
    np.testing.assert_array_equal(overlay.occupied, expected)
    np.testing.assert_array_equal(grid.occupied, base)


def test_high_lidar_noise_marks_phantom_cells() -> None:
    grid = empty_room()
    caster = GridRayCaster(grid)
    lidar = Lidar.from_config(caster, MODEL, Kinematic2DSettings(lidar_beams=90))
    pose = (1.0, 2.0, 0.0)
    quiet = lidar.scan(pose, make_rng(3, SENSOR), 0.0, 0.0, None)
    noisy = lidar.scan(pose, make_rng(3, SENSOR), 0.1, 0.0, None)
    cost_q = RollingCostmap(MODEL)
    cost_n = RollingCostmap(MODEL)
    zeros_d = np.array([], dtype=np.float64)
    cost_q.update(pose, quiet, lidar.beams.angles, zeros_d, zeros_d, grid)
    cost_n.update(pose, noisy, lidar.beams.angles, zeros_d, zeros_d, grid)
    assert cost_n._occupied.sum() >= cost_q._occupied.sum()
