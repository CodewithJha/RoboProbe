"""Regulated pure pursuit (T-033c)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from roboprobe.backends.kinematic2d.controller import pure_pursuit
from roboprobe.backends.kinematic2d.model import Kinematic2DModel

pytestmark = pytest.mark.unit

MODEL = Kinematic2DModel.from_yaml(
    Path(__file__).resolve().parents[5] / "configs" / "backends" / "kinematic2d_v1.yaml"
)
V_MAX = 0.26
CROSS_TRACK_MAX_M = 0.15
DT = 0.05
STEPS = 80


def test_tracks_straight_path() -> None:
    path = np.column_stack([np.linspace(0, 4, 40), np.zeros(40)])
    x, y, yaw = 0.0, 0.05, 0.0
    for _ in range(STEPS):
        v, w = pure_pursuit((x, y, yaw), path, V_MAX, 2.0, MODEL)
        yaw += w * DT
        x += v * DT * np.cos(yaw)
        y += v * DT * np.sin(yaw)
    assert abs(y) < CROSS_TRACK_MAX_M
    assert x > 0.9
