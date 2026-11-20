"""Localisation gain and update (T-033b)."""

from __future__ import annotations

from pathlib import Path

import pytest

from roboprobe.backends.kinematic2d.localization import Localizer, scan_match_gain
from roboprobe.backends.kinematic2d.model import Kinematic2DModel
from roboprobe.core.seeding import LOCALIZATION, make_rng

pytestmark = pytest.mark.unit

MODEL = Kinematic2DModel.from_yaml(
    Path(__file__).resolve().parents[5] / "configs" / "backends" / "kinematic2d_v1.yaml"
)
LOC_ERR_MAX_M = 0.05
STEPS = 40
DT = 0.05
V = 0.2
ODOM_BIAS = 1.02


def test_nominal_gain_keeps_error_below_5cm() -> None:
    loc = Localizer(0.0, 0.0, 0.0, scan_match_gain(MODEL, 0.0, 0.0))
    rng = make_rng(0, LOCALIZATION)
    gt_x = 0.0
    for _ in range(STEPS):
        gt_x += V * DT
        loc.update((V * ODOM_BIAS * DT, 0.0, 0.0), (gt_x, 0.0, 0.0), rng)
    assert abs(loc.x - gt_x) < LOC_ERR_MAX_M


def test_high_lidar_noise_zeroes_gain() -> None:
    assert scan_match_gain(MODEL, MODEL.localization.lidar_noise_ref_m, 0.0) == 0.0
