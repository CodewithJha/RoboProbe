"""Unit tests for docs/19 §5 statistics (T-101a)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats

from roboprobe.core.settings.experiments import ExperimentSettings
from roboprobe.metrics.statistics import (
    a12,
    bootstrap_ci,
    compare,
    effect_label,
    holm,
    mann_whitney_u,
)

pytestmark = pytest.mark.unit

SETTINGS = ExperimentSettings()
A12_TOL = 1e-12


def test_a12_matches_mann_whitney_u_over_n1_n2() -> None:
    # Vargha & Delaney (2000): Â12 = U / (n1 n2) with average ties.
    a = [1.0, 2.0, 3.0, 4.0, 10.0]
    b = [0.5, 2.0, 2.5, 8.0]
    expected = stats.mannwhitneyu(a, b, alternative="two-sided").statistic / (len(a) * len(b))
    assert a12(a, b) == pytest.approx(expected, abs=A12_TOL)


def test_a12_complete_separation_and_ties() -> None:
    assert a12([3.0, 4.0], [1.0, 2.0]) == pytest.approx(1.0, abs=A12_TOL)
    assert a12([1.0, 2.0], [3.0, 4.0]) == pytest.approx(0.0, abs=A12_TOL)
    assert a12([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(0.5, abs=A12_TOL)


def test_a12_empty_is_nan() -> None:
    assert math.isnan(a12([], [1.0]))
    assert math.isnan(a12([1.0], []))


def test_effect_label_bands() -> None:
    # docs/19 §5: negligible < 0.56 ≤ small < 0.64 ≤ medium < 0.71 ≤ large
    assert effect_label(0.50) == "negligible"
    assert effect_label(0.559) == "negligible"
    assert effect_label(0.56) == "small"
    assert effect_label(0.639) == "small"
    assert effect_label(0.64) == "medium"
    assert effect_label(0.709) == "medium"
    assert effect_label(0.71) == "large"
    assert effect_label(1.0) == "large"
    assert effect_label(float("nan")) == "negligible"


def test_mann_whitney_matches_scipy() -> None:
    a = [12.0, 15.0, 18.0, 22.0, 30.0]
    b = [8.0, 9.0, 11.0, 14.0, 40.0]
    u, p = mann_whitney_u(a, b)
    ref = stats.mannwhitneyu(a, b, alternative="two-sided")
    assert u == pytest.approx(float(ref.statistic), abs=A12_TOL)
    assert p == pytest.approx(float(ref.pvalue), abs=A12_TOL)


def test_mann_whitney_empty_and_ties() -> None:
    u, p = mann_whitney_u([], [1.0])
    assert math.isnan(u) and math.isnan(p)
    _u2, p2 = mann_whitney_u([1.0, 1.0, 1.0], [1.0, 1.0])
    assert p2 == pytest.approx(1.0)


def test_holm_worked_example() -> None:
    # Holm (1979) step-down: sorted p multiplied by (m, m-1, …) then made monotone.
    pvals = [0.01, 0.04, 0.03, 0.005]
    got = holm(pvals)
    # sorted: 0.005*4=0.02, 0.01*3=0.03, 0.03*2=0.06, 0.04*1=0.04 → monotone 0.02,0.03,0.06,0.06
    expected = [0.03, 0.06, 0.06, 0.02]
    for a, b in zip(got, expected, strict=True):
        assert a == pytest.approx(b, abs=A12_TOL)


def test_holm_empty_and_already_one() -> None:
    assert holm([]) == []
    assert holm([0.9, 0.8]) == [pytest.approx(1.0), pytest.approx(1.0)]


def test_bootstrap_ci_deterministic_and_degenerate() -> None:
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    rng_a = np.random.default_rng(0)
    rng_b = np.random.default_rng(0)
    a = bootstrap_ci(x, lambda s: float(np.median(s)), n=200, alpha=0.05, rng=rng_a)
    b = bootstrap_ci(x, lambda s: float(np.median(s)), n=200, alpha=0.05, rng=rng_b)
    assert a == b
    lo, hi = bootstrap_ci(
        [4.0, 4.0, 4.0], lambda s: float(np.mean(s)), n=50, rng=np.random.default_rng(1)
    )
    assert lo == pytest.approx(4.0)
    assert hi == pytest.approx(4.0)
    nan_lo, nan_hi = bootstrap_ci([], lambda s: float(np.mean(s)))
    assert math.isnan(nan_lo) and math.isnan(nan_hi)


def test_bootstrap_default_resamples_come_from_settings() -> None:
    assert SETTINGS.bootstrap_resamples == 10000
    assert SETTINGS.alpha == pytest.approx(0.05)


def test_compare_holm_and_a12_against_reference() -> None:
    metric_by_strategy = {
        "S-PROBE": [10.0, 12.0, 11.0, 13.0, 9.0],
        "S-RANDOM": [20.0, 22.0, 19.0, 25.0, 21.0],
        "S-LHS": [14.0, 15.0, 13.0, 16.0, 18.0],
    }
    rng = np.random.default_rng(20261119)
    payload = compare(
        metric_by_strategy,
        metric="MET-02",
        n_resamples=200,
        rng=rng,
        higher_is_better=False,
    )
    tests = payload["tests"]
    assert payload["metrics"] == ["MET-02"]
    assert len(tests) == 2
    raw = [float(row["p"]) for row in tests]
    assert [float(row["p_holm"]) for row in tests] == holm(raw)
    # Lower is better: Â12 = P(PROBE < other) = a12(other, probe)
    by_b = {row["b"]: row for row in tests}
    assert by_b["S-RANDOM"]["a12"] == pytest.approx(
        a12(metric_by_strategy["S-RANDOM"], metric_by_strategy["S-PROBE"]),
        abs=A12_TOL,
    )
    probe = payload["strategies"]["S-PROBE"]["MET-02"]
    assert probe["median"] == pytest.approx(11.0)
    assert probe["iqr"][0] <= probe["median"] <= probe["iqr"][1]
    assert probe["ci95"][0] <= probe["ci95"][1]
