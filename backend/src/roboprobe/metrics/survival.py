"""Kaplan-Meier estimator and two-sample log-rank test (docs/19 §5 step 4).

No ``lifelines`` dependency: both routines are small, seeded-independent, and
tested against a published worked example.

Implements: FR-EXP-002, MET-03 censored comparison.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt
from scipy import stats

__all__ = ["kaplan_meier", "logrank"]

type FloatArray = npt.NDArray[np.float64]
type BoolArray = npt.NDArray[np.bool_]
CHI2_DF = 1
MIN_AT_RISK = 2


def _as_times_events(
    times: Sequence[float], events: Sequence[int | bool]
) -> tuple[FloatArray, BoolArray]:
    """Validate parallel time/event vectors."""
    t = np.asarray(times, dtype=np.float64).reshape(-1)
    e = np.asarray(events, dtype=np.bool_).reshape(-1)
    if t.size != e.size:
        msg = "times and events must have the same length"
        raise ValueError(msg)
    return t, e


def kaplan_meier(
    times: Sequence[float], events: Sequence[int | bool]
) -> tuple[FloatArray, FloatArray]:
    """Right-censored Kaplan-Meier survival curve.

    Event convention: ``events[i]`` is true when ``times[i]`` is an observed
    failure, false when right-censored. Ties: deaths at ``t`` occur before
    censoring at ``t`` (standard KM).

    Args:
        times: Observed or censoring times (MET-03: sims to first failure, or B).
        events: 1/True = failure observed, 0/False = censored.

    Returns:
        ``(t, S)`` including ``(0, 1)`` and a point after every death time.
    """
    t, e = _as_times_events(times, events)
    out_t = [0.0]
    out_s = [1.0]
    if t.size == 0:
        return np.asarray(out_t, dtype=np.float64), np.asarray(out_s, dtype=np.float64)
    order = np.argsort(t, kind="mergesort")
    t = t[order]
    e = e[order]
    n = int(t.size)
    surv = 1.0
    i = 0
    while i < n:
        ti = float(t[i])
        at_risk = n - i
        deaths = 0
        while i < n and float(t[i]) == ti:
            deaths += int(e[i])
            i += 1
        if deaths:
            surv *= 1.0 - deaths / at_risk
            out_t.append(ti)
            out_s.append(surv)
    return np.asarray(out_t, dtype=np.float64), np.asarray(out_s, dtype=np.float64)


def logrank(
    times_a: Sequence[float],
    events_a: Sequence[int | bool],
    times_b: Sequence[float],
    events_b: Sequence[int | bool],
) -> tuple[float, float]:
    """Two-sample Mantel-Haenszel log-rank statistic and chi-square p-value.

    Implements: docs/19 §5 step 4. Formula: Bland & Altman, *The logrank test*,
    BMJ 2004;328:1073.

    Returns:
        ``(chi2, p)`` on 1 df. Degenerate samples (no deaths, or variance 0)
        return ``(0, 1)``.
    """
    ta, ea = _as_times_events(times_a, events_a)
    tb, eb = _as_times_events(times_b, events_b)
    if ta.size == 0 and tb.size == 0:
        return 0.0, 1.0
    times = np.unique(np.concatenate([ta, tb]))
    o_minus_e = 0.0
    variance = 0.0
    for ti in times:
        n_a = int(np.sum(ta >= ti))
        n_b = int(np.sum(tb >= ti))
        n = n_a + n_b
        d_a = int(np.sum((ta == ti) & ea))
        d_b = int(np.sum((tb == ti) & eb))
        d = d_a + d_b
        if d == 0 or n < MIN_AT_RISK:
            continue
        expected_a = n_a * d / n
        o_minus_e += d_a - expected_a
        variance += n_a * n_b * d * (n - d) / (n * n * (n - 1))
    if variance == 0.0:
        return 0.0, 1.0
    chi2 = (o_minus_e * o_minus_e) / variance
    p_value = float(stats.chi2.sf(chi2, CHI2_DF))
    return float(chi2), p_value
