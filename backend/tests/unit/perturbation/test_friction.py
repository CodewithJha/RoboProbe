"""Tests for traction and slip (T-031b; docs/06 §3.5)."""

from __future__ import annotations

import math

import pytest

from roboprobe.perturbation.friction import GRAVITY_MPS2, apply_slip, traction

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("friction", "accel", "expected"),
    [
        (0.8, 0.0, 1.0),  # dry floor, cruising: full traction
        (0.1, 0.0, 0.1 / 0.15),  # slippery floor at rest demand
        (0.1, 0.5, 0.1 / (0.5 / GRAVITY_MPS2 + 0.15)),  # accelerating at a_max = 0.5 m/s²
        (0.2, -0.5, 0.2 / (0.5 / GRAVITY_MPS2 + 0.15)),  # braking: sign ignored
        (0.15, 0.0, 1.0),  # exactly μ_req
        (0.0, 0.3, 0.0),
    ],
)
def test_traction_matches_doc(friction: float, accel: float, expected: float) -> None:
    assert traction(friction, accel) == pytest.approx(expected)


def test_traction_overrides() -> None:
    assert traction(0.1, 0.0, mu_base=0.2) == pytest.approx(0.5)
    assert traction(0.3, 2.0, mu_base=0.1, gravity=10.0) == pytest.approx(1.0)


def test_slip_matches_doc() -> None:
    tau = traction(0.1, 0.5)
    v, w = apply_slip(0.4, 1.0, tau)
    assert v == pytest.approx(0.4 * tau)
    assert w == pytest.approx(tau**1.5)
    assert w < tau  # yaw slips more than translation


def test_full_traction_is_identity() -> None:
    assert apply_slip(0.3, -0.7, 1.0) == (0.3, -0.7)


def test_slip_exponent_override() -> None:
    assert apply_slip(1.0, 1.0, 0.25, yaw_exponent=2.0) == (0.25, 0.0625)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"friction": -0.1, "accel_required": 0.0},
        {"friction": math.nan, "accel_required": 0.0},
        {"friction": 0.5, "accel_required": math.inf},
        {"friction": 0.5, "accel_required": 0.0, "mu_base": 0.0},
        {"friction": 0.5, "accel_required": 0.0, "gravity": -9.8},
    ],
)
def test_invalid_traction_inputs(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="invalid traction inputs"):
        traction(**kwargs)


@pytest.mark.parametrize(
    ("tau", "k"), [(-0.1, 1.5), (1.1, 1.5), (math.nan, 1.5), (0.5, 0.0), (0.5, math.inf)]
)
def test_invalid_slip_inputs(tau: float, k: float) -> None:
    with pytest.raises(ValueError, match="tau"):
        apply_slip(0.1, 0.1, tau, yaw_exponent=k)
