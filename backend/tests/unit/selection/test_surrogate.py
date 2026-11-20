"""RobustnessGP fit/predict/p_fail and scale guard (T-055a, T-055b)."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.stats import norm

from roboprobe.core.errors import ModelFitError
from roboprobe.core.metrics_registry import create_metrics
from roboprobe.core.settings.selection import GpDefaults
from roboprobe.selection.surrogate import RobustnessGP, select_training_subset

pytestmark = [
    pytest.mark.unit,
    pytest.mark.filterwarnings("ignore:.*torch.jit.script.*:FutureWarning"),
]

Z95 = 1.96
CALIBRATION_LO = 0.80
CALIBRATION_HI = 1.0
N_TRAIN = 48
N_HOLD = 80
D = 2


def _toy_rho(x: np.ndarray, rng: np.random.Generator, noise: float = 0.05) -> np.ndarray:
    return np.clip(
        np.sin(2 * np.pi * x[:, 0]) - x[:, 1] + rng.normal(0.0, noise, x.shape[0]), -1.0, 1.0
    )


def test_select_training_subset_keeps_failures_and_bound() -> None:
    n = 20
    x = np.zeros((n, 1))
    y = np.full(n, 0.5)
    y[-3:] = [-0.4, -0.1, 0.05]
    idx = select_training_subset(x, y, max_points=8, boundary_band=0.2)
    assert len(idx) == 8
    assert set(np.flatnonzero(y < 0)).issubset(set(idx.tolist()))


def test_scale_guard_n_5000_keeps_cap_and_failures() -> None:
    rng = np.random.default_rng(0)
    n = 5000
    x = rng.random((n, 3))
    y = rng.uniform(-0.3, 1.0, n)
    y[:40] = -0.5
    gp = GpDefaults()
    idx = select_training_subset(x, y, gp.max_points, boundary_band=0.2)
    assert len(idx) == gp.max_points
    assert set(np.flatnonzero(y < 0)).issubset(set(idx.tolist()))


def test_fit_marks_subsampled() -> None:
    rng = np.random.default_rng(1)
    gp_settings = GpDefaults(max_points=12)
    x = rng.random((30, D))
    y = _toy_rho(x, rng)
    model = RobustnessGP(D, seed=0, gp=gp_settings)
    model.fit(x, y)
    assert model.subsampled
    assert model.lengthscales.shape == (D,)


def test_p_fail_formula_and_seed_determinism() -> None:
    rng = np.random.default_rng(2)
    x = rng.random((N_TRAIN, D))
    y = _toy_rho(x, rng)
    a = RobustnessGP(D, seed=7)
    b = RobustnessGP(D, seed=7)
    a.fit(x, y)
    b.fit(x, y)
    q = rng.random((5, D))
    mean, std = a.predict(q)
    expected = norm.cdf(-mean / np.maximum(std, GpDefaults().noise_lower_bound))
    np.testing.assert_allclose(a.p_fail(q), expected)
    np.testing.assert_allclose(a.predict(q)[0], b.predict(q)[0])
    np.testing.assert_allclose(a.p_fail(q), b.p_fail(q))


def test_calibration_holdout_coverage() -> None:
    """About 95% of hold-out points lie in mean +/- 1.96 total-std (tolerance [0.88, 1])."""
    rng = np.random.default_rng(3)
    x = rng.random((N_TRAIN, D))
    y = _toy_rho(x, rng, noise=0.08)
    model = RobustnessGP(D, seed=3, metrics=create_metrics(enabled=True))
    model.fit(x, y)
    x_h = rng.random((N_HOLD, D))
    y_h = _toy_rho(x_h, rng, noise=0.08)
    mean, _ = model.predict(x_h)
    total = model.predict_total_std(x_h)
    covered = np.mean(np.abs(y_h - mean) <= Z95 * total)
    assert CALIBRATION_LO <= covered <= CALIBRATION_HI, covered


def test_invalid_rows_dropped() -> None:
    rng = np.random.default_rng(4)
    x = rng.random((12, D))
    y = _toy_rho(x, rng)
    y[::3] = np.nan
    model = RobustnessGP(D, seed=1)
    model.fit(x, y)
    mean, std = model.predict(x[:2])
    assert mean.shape == std.shape == (2,)


def test_nan_inputs_raise_model_fit_error() -> None:
    x = np.ones((8, D))
    x[0, 0] = np.nan
    y = np.linspace(-0.2, 0.5, 8)
    with pytest.raises(ModelFitError):
        RobustnessGP(D, seed=0).fit(x, y)


def test_small_n_and_constant_y() -> None:
    x = np.array([[0.1, 0.2], [0.8, 0.9], [0.4, 0.5]])
    y = np.full(3, 0.3)
    model = RobustnessGP(D, seed=0)
    model.fit(x, y)
    mean, std = model.predict(np.array([[0.2, 0.2]]))
    assert mean.shape == std.shape == (1,)
    assert np.all(np.isfinite(mean)) and np.all(np.isfinite(std))


def test_condition_on_observations_does_not_refit_lengthscales() -> None:
    rng = np.random.default_rng(5)
    x = rng.random((20, D))
    y = _toy_rho(x, rng)
    model = RobustnessGP(D, seed=5)
    model.fit(x, y)
    ls = model.lengthscales.copy()
    fantasy = model.condition_on_observations(np.array([0.2, 0.3]), np.array([0.0]))
    np.testing.assert_allclose(fantasy.lengthscales, ls)
    assert model.botorch_model() is not fantasy.botorch_model()
