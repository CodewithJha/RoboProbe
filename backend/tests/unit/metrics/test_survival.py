"""Kaplan-Meier and log-rank tests for MET-03 (T-101b)."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from roboprobe.metrics.survival import kaplan_meier, logrank

pytestmark = pytest.mark.unit
TOL = 1e-12
PUBLISHED_TOL = 1e-6


def test_kaplan_meier_hand_computed_with_censor() -> None:
    # Times 1, 2, 3 (events) and 4 (censored): n=4
    # S(1)=3/4, S(2)=(3/4)*(2/3)=1/2, S(3)=(1/2)*(1/2)=1/4; t=4 does not drop S.
    t, s = kaplan_meier([1.0, 2.0, 3.0, 4.0], [1, 1, 1, 0])
    np.testing.assert_allclose(t, [0.0, 1.0, 2.0, 3.0], atol=TOL)
    np.testing.assert_allclose(s, [1.0, 0.75, 0.5, 0.25], atol=TOL)


def test_kaplan_meier_all_censored_and_empty() -> None:
    t, s = kaplan_meier([5.0, 8.0], [0, 0])
    np.testing.assert_allclose(t, [0.0])
    np.testing.assert_allclose(s, [1.0])
    t0, s0 = kaplan_meier([], [])
    np.testing.assert_allclose(t0, [0.0])
    np.testing.assert_allclose(s0, [1.0])


def test_kaplan_meier_tied_deaths() -> None:
    # Two deaths at t=2 among 3 at risk: S = 1/3.
    t, s = kaplan_meier([2.0, 2.0, 5.0], [1, 1, 0])
    np.testing.assert_allclose(t, [0.0, 2.0], atol=TOL)
    np.testing.assert_allclose(s, [1.0, 1.0 / 3.0], atol=TOL)


def test_logrank_hand_computed_two_groups() -> None:
    # A: 3 (event), 5 (censor). B: 2 (event), 6 (event).
    # t=2: nA=2,nB=2,n=4,d=1,dA=0 → E_A=0.5, V=0.25
    # t=3: nA=2,nB=1,n=3,d=1,dA=1 → E_A=2/3, V=2/9
    # t=6: nA=0 skipped (n<2 after A censored at 5)
    o_minus_e = (0.0 - 0.5) + (1.0 - 2.0 / 3.0)
    variance = 0.25 + (2.0 / 9.0)
    chi2_expected = (o_minus_e**2) / variance
    chi2, p = logrank([3.0, 5.0], [1, 0], [2.0, 6.0], [1, 1])
    assert chi2 == pytest.approx(chi2_expected, abs=TOL)
    assert p == pytest.approx(float(stats.chi2.sf(chi2_expected, 1)), abs=TOL)


def test_logrank_freireich_1963_6mp_vs_control() -> None:
    """Mantel-Haenszel log-rank on Freireich 1963 6-MP vs control (BMJ 2004).

    6-MP (n=21, + = censored): 6,6,6,6+,7,9+,10,10+,11+,13,16,17+,19+,20+,22,23,25+,32+,32+,34+,35+
    Control (n=21, all events): 1,1,2,2,3,4,4,5,5,8,8,8,8,11,11,12,12,15,17,22,23
    """
    mp_times = [
        6,
        6,
        6,
        6,
        7,
        9,
        10,
        10,
        11,
        13,
        16,
        17,
        19,
        20,
        22,
        23,
        25,
        32,
        32,
        34,
        35,
    ]
    mp_events = [
        1,
        1,
        1,
        0,
        1,
        0,
        1,
        0,
        0,
        1,
        1,
        0,
        0,
        0,
        1,
        1,
        0,
        0,
        0,
        0,
        0,
    ]
    ctrl_times = [1, 1, 2, 2, 3, 4, 4, 5, 5, 8, 8, 8, 8, 11, 11, 12, 12, 15, 17, 22, 23]
    ctrl_events = [1] * len(ctrl_times)
    chi2, p = logrank(mp_times, mp_events, ctrl_times, ctrl_events)
    # Published Mantel-Haenszel chi-square ~ 16.79 on 1 df (Freireich / BMJ 2004).
    assert chi2 == pytest.approx(16.7929, abs=1e-3)
    assert p == pytest.approx(float(stats.chi2.sf(chi2, 1)), abs=PUBLISHED_TOL)
    assert p < 1e-4


def test_logrank_degenerate() -> None:
    chi2, p = logrank([10.0, 12.0], [0, 0], [8.0], [0])
    assert chi2 == 0.0 and p == 1.0
    chi2_e, p_e = logrank([], [], [], [])
    assert chi2_e == 0.0 and p_e == 1.0


def test_kaplan_meier_length_mismatch() -> None:
    with pytest.raises(ValueError, match="same length"):
        kaplan_meier([1.0, 2.0], [1])
