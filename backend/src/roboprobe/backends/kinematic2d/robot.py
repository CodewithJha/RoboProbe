"""Unicycle kinematics with accel limits, friction slip and command delay (docs/10 §7.1).

Implements: FR-SIM-001
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from roboprobe.backends.kinematic2d.model import Kinematic2DModel
from roboprobe.perturbation.delay import CommandDelayBuffer
from roboprobe.perturbation.friction import apply_slip, traction

__all__ = ["RobotState", "step"]


@dataclass(slots=True)
class RobotState:
    """Ground-truth pose/twist plus odometry that reports commanded wheel motion."""

    x: float
    y: float
    yaw: float
    v: float
    w: float
    odom_x: float
    odom_y: float
    odom_yaw: float
    meas_v: float
    meas_w: float


def _clip_accel(current: float, target: float, limit: float, dt: float) -> float:
    delta = target - current
    max_delta = limit * dt
    if delta > max_delta:
        return current + max_delta
    if delta < -max_delta:
        return current - max_delta
    return target


def step(  # noqa: PLR0913,PLR0917
    state: RobotState,
    cmd: tuple[float, float],
    dt: float,
    model: Kinematic2DModel,
    friction: float,
    delay: CommandDelayBuffer[tuple[float, float]],
    t: float,
) -> RobotState:
    """Integrate one step. ``cmd`` is ``(v, ω)`` published at ``t``; delay is applied first."""
    delay.push(t, cmd)
    due = delay.pop_due(t)
    v_pub, w_pub = due[-1] if due else (0.0, 0.0)
    robot = model.robot
    v_limited = _clip_accel(state.v, v_pub, robot.a_max_mps2, dt)
    w_limited = _clip_accel(state.w, w_pub, robot.alpha_max_radps2, dt)
    accel = abs(v_limited - state.v) / dt if dt > 0.0 else 0.0
    tau = traction(friction, accel)
    v_real, w_real = apply_slip(v_limited, w_limited, tau)
    cos_yaw, sin_yaw = math.cos(state.yaw), math.sin(state.yaw)
    state.x += v_real * dt * cos_yaw
    state.y += v_real * dt * sin_yaw
    state.yaw += w_real * dt
    cos_o, sin_o = math.cos(state.odom_yaw), math.sin(state.odom_yaw)
    state.odom_x += v_limited * dt * cos_o
    state.odom_y += v_limited * dt * sin_o
    state.odom_yaw += w_limited * dt
    state.v = v_limited
    state.w = w_limited
    state.meas_v = v_real
    state.meas_w = w_real
    return state
