"""Tests for lidar noise and dropout (T-031a; docs/06 §3.4)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from roboprobe.core.seeding import RUN, SENSOR, make_rng
from roboprobe.perturbation.lidar import apply_dropout, apply_lidar_noise

pytestmark = pytest.mark.unit

R_MIN, R_MAX = 0.15, 12.0
SEED = 1234
N_BEAMS = 100_000
SIGMA_BOUND = 4.0  # z-score accepted by the statistical checks (false alarm ~6e-5)


def sensor_rng(seed: int = SEED) -> np.random.Generator:
    return make_rng(seed, RUN, 0, SENSOR)


def test_noise_matches_formula() -> None:
    ranges = np.array([1.0, 5.0, 11.99, 0.16])
    std = 0.05
    expected_noise = sensor_rng().normal(0.0, std, size=ranges.shape)
    out = apply_lidar_noise(ranges, std, sensor_rng(), R_MIN, R_MAX)
    np.testing.assert_array_equal(out, np.clip(ranges + expected_noise, R_MIN, R_MAX))


def test_noise_statistics() -> None:
    std = 0.05
    out = apply_lidar_noise(np.full(N_BEAMS, 5.0), std, sensor_rng(), R_MIN, R_MAX)
    residual = out - 5.0
    assert abs(residual.mean()) < SIGMA_BOUND * std / math.sqrt(N_BEAMS)
    assert residual.std() == pytest.approx(std, rel=0.02)


def test_noise_is_clipped_to_sensor_limits() -> None:
    ranges = np.concatenate([np.full(1000, R_MIN), np.full(1000, R_MAX)])
    out = apply_lidar_noise(ranges, 1.0, sensor_rng(), R_MIN, R_MAX)
    assert out.min() == R_MIN
    assert out.max() == R_MAX


def test_zero_std_is_identity_but_consumes_the_stream() -> None:
    ranges = np.linspace(R_MIN, R_MAX, 50)
    rng_used, rng_ref = sensor_rng(), sensor_rng()
    np.testing.assert_array_equal(apply_lidar_noise(ranges, 0.0, rng_used, R_MIN, R_MAX), ranges)
    rng_ref.normal(size=ranges.shape)
    assert rng_used.random() == rng_ref.random()


def test_non_finite_beams_are_preserved() -> None:
    ranges = np.array([np.inf, np.nan, 3.0])
    out = apply_lidar_noise(ranges, 0.5, sensor_rng(), R_MIN, R_MAX)
    assert out[0] == np.inf
    assert math.isnan(out[1])
    assert R_MIN <= out[2] <= R_MAX


def test_inputs_are_not_mutated_and_shape_is_kept() -> None:
    ranges = np.full((3, 4), 2.0)
    before = ranges.copy()
    noisy = apply_lidar_noise(ranges, 0.1, sensor_rng(), R_MIN, R_MAX)
    dropped = apply_dropout(ranges, 0.5, sensor_rng())
    np.testing.assert_array_equal(ranges, before)
    assert noisy.shape == dropped.shape == ranges.shape
    assert noisy.dtype == dropped.dtype == np.float64


def test_accepts_lists() -> None:
    assert apply_dropout([1.0, 2.0], 0.0, sensor_rng()).tolist() == [1.0, 2.0]


def test_same_seed_identical_outputs() -> None:
    ranges = np.linspace(R_MIN, R_MAX, 360)
    first = apply_dropout(
        apply_lidar_noise(ranges, 0.05, sensor_rng(), R_MIN, R_MAX), 0.1, sensor_rng()
    )
    second = apply_dropout(
        apply_lidar_noise(ranges, 0.05, sensor_rng(), R_MIN, R_MAX), 0.1, sensor_rng()
    )
    np.testing.assert_array_equal(first, second)
    other = apply_lidar_noise(ranges, 0.05, sensor_rng(SEED + 1), R_MIN, R_MAX)
    assert not np.array_equal(apply_lidar_noise(ranges, 0.05, sensor_rng(), R_MIN, R_MAX), other)


@pytest.mark.parametrize("p", [0.05, 0.2, 0.5])
def test_dropout_fraction_within_binomial_ci(p: float) -> None:
    out = apply_dropout(np.full(N_BEAMS, 3.0), p, sensor_rng())
    dropped = np.isinf(out)
    half_width = SIGMA_BOUND * math.sqrt(p * (1 - p) / N_BEAMS)
    assert abs(dropped.mean() - p) < half_width
    assert np.all(out[~dropped] == 3.0)


def test_dropout_extremes() -> None:
    ranges = np.full(1000, 3.0)
    np.testing.assert_array_equal(apply_dropout(ranges, 0.0, sensor_rng()), ranges)
    assert np.all(np.isinf(apply_dropout(ranges, 1.0, sensor_rng())))


@pytest.mark.parametrize("std", [-0.1, math.nan, math.inf])
def test_invalid_std(std: float) -> None:
    with pytest.raises(ValueError, match="std"):
        apply_lidar_noise([1.0], std, sensor_rng(), R_MIN, R_MAX)


@pytest.mark.parametrize(("r_min", "r_max"), [(-0.1, 1.0), (2.0, 1.0), (1.0, 1.0), (0.0, math.inf)])
def test_invalid_range_limits(r_min: float, r_max: float) -> None:
    with pytest.raises(ValueError, match="r_min"):
        apply_lidar_noise([1.0], 0.1, sensor_rng(), r_min, r_max)


@pytest.mark.parametrize("p", [-0.01, 1.01, math.nan])
def test_invalid_dropout_probability(p: float) -> None:
    with pytest.raises(ValueError, match="probability"):
        apply_dropout([1.0], p, sensor_rng())
