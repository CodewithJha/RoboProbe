"""Floor friction traction and slip for kinematic2d (P5) — docs/06 §3.5.

``τ = min(1, P5 / μ_req)`` with ``μ_req = |a| / g + μ_base``; realised motion
``v_real = v_cmd · τ`` and ``ω_real = ω_cmd · τ^k`` (``k = 1.5``). Odometry keeps reporting the
commanded wheel motion, which is what produces odometry drift on slippery floors.

``μ_base`` and ``k`` are the documented model constants, exposed as named defaults so the
kinematic2d model file (T-029/T-034 calibration) can override them per call. Gazebo applies P5
directly to the ground plane instead (``mu``/``mu2``).
"""

from __future__ import annotations

import math

__all__ = ["GRAVITY_MPS2", "MU_BASE", "YAW_SLIP_EXPONENT", "apply_slip", "traction"]

GRAVITY_MPS2 = 9.80665
"""Standard gravity [m/s²] (ISO 80000-3)."""
MU_BASE = 0.15
"""Friction needed at zero acceleration (rolling/turning losses), docs/06 §3.5."""
YAW_SLIP_EXPONENT = 1.5
"""Exponent of the yaw-rate slip ``ω_real = ω_cmd · τ^k``, docs/06 §3.5."""


def traction(
    friction: float,
    accel_required: float,
    *,
    mu_base: float = MU_BASE,
    gravity: float = GRAVITY_MPS2,
) -> float:
    """Effective traction ``τ = min(1, friction / (|a| / g + mu_base))`` in ``[0, 1]``.

    Args:
        friction: Floor friction coefficient P5, ``>= 0``.
        accel_required: Acceleration demanded by the controller [m/s²]; sign is ignored.
        mu_base: Friction required at zero acceleration, ``> 0``.
        gravity: Gravitational acceleration [m/s²], ``> 0``.

    Raises:
        ValueError: On non-finite inputs, negative friction or non-positive ``mu_base``/``gravity``.
    """
    values = {
        "friction": friction,
        "accel_required": accel_required,
        "mu_base": mu_base,
        "gravity": gravity,
    }
    bad = [name for name, value in values.items() if not math.isfinite(value)]
    if bad or friction < 0.0 or mu_base <= 0.0 or gravity <= 0.0:
        rule = "finite, friction >= 0, mu_base > 0, gravity > 0"
        msg = f"invalid traction inputs {values} (need {rule})"
        raise ValueError(msg)
    mu_required = abs(accel_required) / gravity + mu_base
    return min(1.0, friction / mu_required)


def apply_slip(
    v_cmd: float,
    w_cmd: float,
    tau: float,
    *,
    yaw_exponent: float = YAW_SLIP_EXPONENT,
) -> tuple[float, float]:
    """Realised ``(v, ω)`` for commanded ``(v_cmd, w_cmd)`` under traction ``tau``.

    Args:
        v_cmd: Commanded linear velocity [m/s].
        w_cmd: Commanded yaw rate [rad/s].
        tau: Traction from :func:`traction`, in ``[0, 1]``.
        yaw_exponent: Yaw slip exponent ``k``, ``> 0``.

    Raises:
        ValueError: If ``tau`` is outside ``[0, 1]`` or ``yaw_exponent`` is not positive.
    """
    if not 0.0 <= tau <= 1.0 or not (math.isfinite(yaw_exponent) and yaw_exponent > 0.0):
        msg = f"need 0 <= tau <= 1 and yaw_exponent > 0, got tau={tau}, yaw_exponent={yaw_exponent}"
        raise ValueError(msg)
    return v_cmd * tau, w_cmd * tau**yaw_exponent
