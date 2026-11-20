"""Unit tests for VolumeEstimator and Wilson intervals (T-077)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from scipy.stats import norm

from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.settings.analysis import RiskThresholds
from roboprobe.risk.mapper import RiskMapper
from roboprobe.risk.stats import wilson_interval
from roboprobe.risk.volume import RegionVolumes, VolumeEstimator, robustness_score
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.selection.benchmarks import multi_mode_6d

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[4]
MULTI = REPO / "configs" / "scenario_spaces" / "multi_mode_6d.yaml"
BRANIN = REPO / "configs" / "scenario_spaces" / "branin_2d.yaml"

# Hard-coded Wilson references at alpha=0.05 (cross-checked against
# statsmodels.stats.proportion.proportion_confint method="wilson"; not a runtime dep).
_WILSON_REF: tuple[tuple[int, int, tuple[float, float]], ...] = (
    (0, 10, (0.0, 0.2775327998628892)),
    (5, 10, (0.236593090512564, 0.763406909487436)),
    (10, 10, (0.7224672001371106, 1.0)),
    (50, 200, (0.195081680068175, 0.31434098312045833)),
)


class _MultiModeGP:
    """Noise-free multi_mode_6d as a near-hard classifier via tiny posterior std."""

    def predict(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        rows = np.asarray(x, dtype=np.float64)
        mean = np.asarray([multi_mode_6d(row, noise=0.0) for row in rows], dtype=np.float64)
        std = np.full(rows.shape[0], 1e-9, dtype=np.float64)
        return mean, std

    def predict_total_std(self, x: np.ndarray) -> np.ndarray:
        return self.predict(x)[1]


class _SafeGP:
    def predict(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        n = np.asarray(x).shape[0]
        return np.ones(n), np.full(n, 0.1)

    def predict_total_std(self, x: np.ndarray) -> np.ndarray:
        return self.predict(x)[1]


@pytest.mark.parametrize(("k", "n", "expected"), _WILSON_REF)
def test_wilson_matches_statsmodels_reference(
    k: int, n: int, expected: tuple[float, float]
) -> None:
    z = float(norm.ppf(1.0 - 0.05 / 2.0))
    low, high = wilson_interval(k, n, z=z)
    assert low == pytest.approx(expected[0], rel=0, abs=1e-9)
    assert high == pytest.approx(expected[1], rel=0, abs=1e-9)


def test_estimate_reproducible_and_fractions_sum() -> None:
    space = ScenarioSpace.from_yaml(BRANIN, base_dir=REPO)
    mapper = RiskMapper(_SafeGP(), space, RiskThresholds())
    est = VolumeEstimator(alpha=0.05)
    a = est.estimate(mapper, n=256, seed=3)
    b = est.estimate(mapper, n=256, seed=3)
    assert a == b
    assert abs(a.safe + a.uncertain + a.failure - 1.0) <= 1e-12
    assert a.safe == pytest.approx(1.0)


def test_multi_mode_failure_volume_within_ci() -> None:
    cfg = RoboProbeSettings().selection.benchmarks
    space = ScenarioSpace.from_yaml(MULTI, base_dir=REPO)
    mapper = RiskMapper(_MultiModeGP(), space, RiskThresholds(safe=0.05, failure=0.95))
    n = int(RoboProbeSettings().risk.volume_samples)
    vol = VolumeEstimator(alpha=0.05).estimate(mapper, n=n, seed=0)
    assert vol.failure_ci[0] <= cfg.failure_volume_target <= vol.failure_ci[1]
    assert abs(vol.failure - cfg.failure_volume_target) <= cfg.failure_volume_atol


@given(
    safe=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    uncertain=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=40, deadline=None)
def test_robustness_score_in_unit_interval(safe: float, uncertain: float) -> None:
    if safe + uncertain > 1.0:
        return
    failure = 1.0 - safe - uncertain
    vol = RegionVolumes(
        safe=safe,
        uncertain=uncertain,
        failure=failure,
        safe_ci=(0.0, 1.0),
        uncertain_ci=(0.0, 1.0),
        failure_ci=(0.0, 1.0),
        n=100,
        seed=0,
    )
    score = robustness_score(vol)
    assert 0.0 <= score <= 1.0
