"""Unicycle kinematics (T-033a)."""

from __future__ import annotations

from pathlib import Path

import pytest

from roboprobe.backends.kinematic2d.model import Kinematic2DModel
from roboprobe.backends.kinematic2d.robot import RobotState, step
from roboprobe.perturbation.delay import CommandDelayBuffer

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]
MODEL = Kinematic2DModel.from_yaml(REPO / "configs" / "backends" / "kinematic2d_v1.yaml")
DT = 0.05
DRY_FRICTION = 1.0
ICE_FRICTION = 0.1


def origin() -> RobotState:
    return RobotState(
        x=0.0,
        y=0.0,
        yaw=0.0,
        v=0.0,
        w=0.0,
        odom_x=0.0,
        odom_y=0.0,
        odom_yaw=0.0,
        meas_v=0.0,
        meas_w=0.0,
    )


def integrate(cmd: tuple[float, float], n: int, friction: float) -> RobotState:
    delay: CommandDelayBuffer[tuple[float, float]] = CommandDelayBuffer(0.0)
    state = origin()
    for i in range(n):
        state = step(state, cmd, DT, MODEL, friction, delay, i * DT)
    return state


def test_straight_line_and_accel_limit() -> None:
    n = 20
    state = integrate((1.0, 0.0), n, DRY_FRICTION)
    vmax = MODEL.robot.a_max_mps2 * n * DT
    assert state.v == pytest.approx(min(1.0, vmax))
    assert state.x > 0
    assert state.y == pytest.approx(0.0)


def test_turn_changes_yaw() -> None:
    state = integrate((0.0, 1.0), 10, DRY_FRICTION)
    assert state.yaw > 0


def test_slip_reduces_realised_velocity_and_odometry_drifts() -> None:
    dry = integrate((0.3, 0.0), 40, DRY_FRICTION)
    ice = integrate((0.3, 0.0), 40, ICE_FRICTION)
    assert ice.x < dry.x
    assert ice.odom_x > ice.x
