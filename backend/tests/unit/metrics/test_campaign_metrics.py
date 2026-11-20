"""Hand-computed campaign metrics MET-01/03/05/06/07 (T-100a)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from roboprobe.core.types import FailureClass, Verdict
from roboprobe.metrics.campaign_metrics import (
    SECONDS_PER_HOUR,
    CampaignRun,
    Replay,
    cost_per_mode,
    failure_discovery_rate,
    first_failure,
    reproducibility,
    robustness_delta,
    robustness_score,
)

pytestmark = pytest.mark.unit


def _run(verdict: Verdict, t: float = 1.0, **kwargs: object) -> CampaignRun:
    return CampaignRun(verdict=verdict, wall_time_s=float(t), **kwargs)  # type: ignore[arg-type]


def test_fdr_mixed_valid_invalid_and_confirm_excluded() -> None:
    runs = [
        _run(Verdict.PASS, 2.0),
        _run(Verdict.FAIL, 3.0),
        _run(Verdict.INVALID, 4.0),
        _run(Verdict.FAIL, 5.0, phase="confirm"),
        _run(Verdict.FAIL, 6.0, tags=("confirm",)),
        _run(Verdict.FAIL, 1.0),
    ]
    fdr, fdr_h = failure_discovery_rate(runs)
    # V = PASS+FAIL+INVALID = 3 comparison valid? INVALID not in V, F=2, V=2 PASS+2 FAIL wait
    # comparison: PASS, FAIL, INVALID, FAIL → V=3, F=2, FDR=2/3
    assert fdr == pytest.approx(2 / 3)
    total_s = 2.0 + 3.0 + 4.0 + 1.0
    assert fdr_h == pytest.approx(2 / (total_s / SECONDS_PER_HOUR))


def test_fdr_no_failures() -> None:
    runs = [_run(Verdict.PASS, 1.0), _run(Verdict.PASS, 1.0)]
    fdr, fdr_h = failure_discovery_rate(runs)
    assert fdr == 0.0
    assert fdr_h == 0.0


def test_fdr_all_invalid() -> None:
    runs = [_run(Verdict.INVALID, 1.0), _run(Verdict.INVALID, 2.0)]
    fdr, fdr_h = failure_discovery_rate(runs)
    assert math.isnan(fdr)
    assert fdr_h == pytest.approx(0.0)


def test_fdr_zero_time_is_nan() -> None:
    fdr, fdr_h = failure_discovery_rate([_run(Verdict.FAIL, 0.0)])
    assert fdr == 1.0
    assert math.isnan(fdr_h)


def test_first_failure_found_and_censored() -> None:
    found = first_failure(
        [
            _run(Verdict.PASS),
            _run(Verdict.FAIL, phase="confirm"),
            _run(Verdict.FAIL),
        ]
    )
    assert found.n1 == 2 and found.censored is False
    none = first_failure([_run(Verdict.PASS), _run(Verdict.INVALID)], budget=10)
    assert none.n1 == 10 and none.censored is True
    empty = first_failure([])
    assert empty.n1 == 0 and empty.censored is True


def test_cost_per_mode_finite_and_infinite() -> None:
    runs = [_run(Verdict.PASS, 2.0), _run(Verdict.FAIL, 3.0), _run(Verdict.FAIL, 5.0)]
    cpm, spm = cost_per_mode(runs, n_modes=2)
    assert cpm == pytest.approx(5.0)
    assert spm == pytest.approx(1.5)
    inf_cpm, inf_spm = cost_per_mode(runs, n_modes=0)
    assert math.isinf(inf_cpm) and math.isinf(inf_spm)


def test_reproducibility_mean_over_modes() -> None:
    expected = {
        "FM-01": Replay(Verdict.FAIL, FailureClass.COL),
        "FM-02": Replay(Verdict.FAIL, FailureClass.TIMEOUT),
    }
    replays = {
        "FM-01": [Replay(Verdict.FAIL, FailureClass.COL)] * 5,
        "FM-02": [Replay(Verdict.FAIL, FailureClass.TIMEOUT)] * 4 + [Replay(Verdict.PASS, None)],
    }
    assert reproducibility(expected, replays) == pytest.approx(0.9)


def test_reproducibility_empty_and_class_mismatch() -> None:
    assert math.isnan(reproducibility({}, {}))
    expected = {"FM-01": Replay(Verdict.FAIL, FailureClass.COL)}
    replays = {"FM-01": [Replay(Verdict.FAIL, FailureClass.NEAR)] * 5}
    assert reproducibility(expected, replays) == 0.0


def test_robustness_score_formula() -> None:
    labels = ["SAFE", "SAFE", "UNCERTAIN", "FAILURE"]
    # 1 - 1/4 - 0.5*(1/4) = 0.625
    assert robustness_score(labels) == pytest.approx(0.625)
    assert math.isnan(robustness_score([]))


def test_robustness_delta_paired_bootstrap() -> None:
    labels_a = ["FAILURE", "FAILURE", "SAFE", "SAFE"]
    labels_b = ["SAFE", "SAFE", "SAFE", "SAFE"]
    delta, ci = robustness_delta(labels_a, labels_b, n_resamples=200, rng=np.random.default_rng(0))
    # score A = 1 - 0.5 - 0 = 0.5; B = 1; Δ = 0.5
    assert delta == pytest.approx(0.5)
    assert ci[0] <= delta <= ci[1]
    d0, ci0 = robustness_delta(
        ["SAFE", "SAFE"], ["SAFE", "SAFE"], n_resamples=40, rng=np.random.default_rng(1)
    )
    assert d0 == pytest.approx(0.0)
    assert ci0 == (pytest.approx(0.0), pytest.approx(0.0))


def test_robustness_delta_length_mismatch() -> None:
    with pytest.raises(ValueError, match="same length"):
        robustness_delta(["SAFE"], ["SAFE", "FAILURE"])
