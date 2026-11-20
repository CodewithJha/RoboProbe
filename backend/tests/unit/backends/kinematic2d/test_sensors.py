"""Lidar and depth sensors (T-033a)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from roboprobe.backends.kinematic2d.model import Kinematic2DModel
from roboprobe.backends.kinematic2d.sensors import DepthCamera, Lidar
from roboprobe.core.seeding import PERCEPTION as PERCEPTION_STREAM
from roboprobe.core.seeding import SENSOR, make_rng
from roboprobe.core.settings.backends import Kinematic2DSettings
from roboprobe.geometry import GridRayCaster, OccupancyGrid, Rect
from roboprobe.perturbation.perception import PerceptionModel

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]
MODEL = Kinematic2DModel.from_yaml(REPO / "configs" / "backends" / "kinematic2d_v1.yaml")
OAKD = PerceptionModel.from_yaml(REPO / "configs" / "perception" / "oakd_lowlight_v1.yaml")
RES = 0.05
ROOM = 80


def hall() -> OccupancyGrid:
    occupied = np.zeros((ROOM, ROOM), dtype=bool)
    occupied[0, :] = occupied[-1, :] = occupied[:, 0] = occupied[:, -1] = True
    return OccupancyGrid(occupied, RES)


def test_lidar_ignores_pallet_depth_sees_it() -> None:
    grid = hall()
    caster = GridRayCaster(grid)
    settings = Kinematic2DSettings(lidar_beams=36, depth_beams=12)
    lidar = Lidar.from_config(caster, MODEL, settings)
    depth = DepthCamera.from_config(caster, MODEL, settings, OAKD)
    pose = np.array([1.0, 2.0, 0.0])
    pallet = Rect(x=2.0, y=2.0, yaw=0.0, length=0.8, width=0.6)
    rng_s = make_rng(1, SENSOR)
    rng_p = make_rng(1, PERCEPTION_STREAM)
    lidar_ranges = lidar.scan(pose, rng_s, 0.0, 0.0, pallet)
    depth_ranges = depth.scan(pose, pallet, 300.0, rng_p)
    # Forward lidar beam should see the far wall, not the pallet.
    forward = int(np.argmin(np.abs(lidar.beams.angles)))
    assert lidar_ranges[forward] > 1.5
    forward_d = int(np.argmin(np.abs(depth.beams.angles)))
    assert depth_ranges[forward_d] < lidar_ranges[forward]


def test_depth_range_shrinks_in_the_dark() -> None:
    grid = hall()
    caster = GridRayCaster(grid)
    depth = DepthCamera.from_config(caster, MODEL, Kinematic2DSettings(depth_beams=12), OAKD)
    pose = np.array([1.0, 2.0, 0.0])
    bright = depth.scan(pose, None, 300.0, make_rng(2, PERCEPTION_STREAM))
    dark = depth.scan(pose, None, 5.0, make_rng(2, PERCEPTION_STREAM))
    finite_dark = np.isfinite(dark)
    assert finite_dark.sum() <= np.isfinite(bright).sum()
    assert OAKD.r_max(OAKD.eta(5.0)) < OAKD.r_max(OAKD.eta(300.0))
