"""Statistical analysis protocol (docs/19 §5, FR-EXP-002).

Implements: FR-EXP-002, MET comparison tests (Mann-Whitney U, A12, bootstrap CI, Holm).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Literal

import numpy as np
import numpy.typing as npt
from scipy import stats

from roboprobe.core.settings.experiments import ExperimentSettings

__all__ = [
    "EffectSize",
    "MetricSummary",
    "PairwiseTest",
    "a12",
    "bootstrap_ci",
    "compare",
    "effect_label",
    "holm",
    "mann_whitney_u",
]

type FloatArray = npt.NDArray[np.float64]
type StatFn = Callable[[FloatArray], float]
EffectSize = Literal["negligible", "small", "medium", "large"]

# Vargha-Delaney (2000) A12 bands (docs/19 §5 step 2).
_A12_SMALL = 0.56
_A12_MEDIUM = 0.64
_A12_LARGE = 0.71

_EXPERIMENT = ExperimentSettings()
_DEFAULT_RESAMPLES = _EXPERIMENT.bootstrap_resamples
_DEFAULT_ALPHA = _EXPERIMENT.alpha
_DEFAULT_REFERENCE = "S-PROBE"
_MWU_NAME = "mann_whitney_u"


class MetricSummary(dict[str, float | list[float]]):
    """Per-strategy metric location summary (docs/12 §3.5)."""


class PairwiseTest(dict[str, str | float]):
    """One pairwise test row of ``ExperimentComparison.tests`` (docs/12 §3.5)."""


def _as_float_array(x: npt.ArrayLike) -> FloatArray:
    """Copy ``x`` as a 1-d float64 array."""
    return np.asarray(x, dtype=np.float64).reshape(-1)


def a12(a: Sequence[float] | npt.ArrayLike, b: Sequence[float] | npt.ArrayLike) -> float:
    """Vargha-Delaney A12: P(A > B) + 0.5 P(A = B).

    Implements: docs/19 §5 step 2. Equals Mann-Whitney U / (n_a n_b) with average ties.

    Args:
        a: Sample A (typically the reference strategy).
        b: Sample B.

    Returns:
        A12 in ``[0, 1]``, or ``nan`` if either sample is empty.
    """
    aa = _as_float_array(a)
    bb = _as_float_array(b)
    n_a = aa.size
    n_b = bb.size
    if n_a == 0 or n_b == 0:
        return float("nan")
    greater = np.sum(aa[:, np.newaxis] > bb)
    ties = np.sum(aa[:, np.newaxis] == bb)
    return float((greater + 0.5 * ties) / (n_a * n_b))


def effect_label(a12_value: float) -> EffectSize:
    """Map A12 onto the Vargha-Delaney magnitude labels (docs/19 §5).

    Bands: negligible < 0.56 <= small < 0.64 <= medium < 0.71 <= large.
    Values below 0.5 (A tends to be smaller) are labelled ``negligible``.
    """
    if not np.isfinite(a12_value) or a12_value < _A12_SMALL:
        return "negligible"
    if a12_value < _A12_MEDIUM:
        return "small"
    if a12_value < _A12_LARGE:
        return "medium"
    return "large"


def mann_whitney_u(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    """Two-sided Mann-Whitney U (SciPy) and p-value (docs/19 §5 step 1).

    Returns:
        ``(U_a, p)``. ``(nan, nan)`` if either sample is empty.
    """
    aa = _as_float_array(a)
    bb = _as_float_array(b)
    if aa.size == 0 or bb.size == 0:
        return float("nan"), float("nan")
    result = stats.mannwhitneyu(aa, bb, alternative="two-sided")
    p_value = float(result.pvalue)
    if not np.isfinite(p_value):
        # All observations identical: U is defined, two-sided p is 1.
        p_value = 1.0
    return float(result.statistic), p_value


def bootstrap_ci(
    x: npt.ArrayLike,
    stat: StatFn,
    n: int = _DEFAULT_RESAMPLES,
    alpha: float = _DEFAULT_ALPHA,
    rng: np.random.Generator | None = None,
) -> tuple[float, float]:
    """Percentile bootstrap CI of ``stat(x)`` (docs/19 §5 step 3).

    Args:
        x: Observed sample.
        stat: Statistic mapped over each resample.
        n: Number of resamples (``experiments.bootstrap_resamples``).
        alpha: Two-sided level (``experiments.alpha``); the CI is ``1 - alpha``.
        rng: Injected generator; a fresh default_rng is used when omitted.

    Returns:
        ``(lo, hi)`` percentile bounds, or ``(nan, nan)`` if ``x`` is empty.
    """
    xx = _as_float_array(x)
    if xx.size == 0:
        return float("nan"), float("nan")
    generator = np.random.default_rng() if rng is None else rng
    draws = generator.choice(xx, size=(n, xx.size), replace=True)
    samples = np.apply_along_axis(stat, 1, draws)
    q_lo = 100.0 * (alpha / 2.0)
    q_hi = 100.0 * (1.0 - alpha / 2.0)
    lo, hi = np.percentile(samples, [q_lo, q_hi])
    return float(lo), float(hi)


def holm(pvalues: Sequence[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values, returned in input order (Holm 1979).

    Implements: docs/19 §5 step 1.
    """
    p = np.asarray(pvalues, dtype=np.float64)
    m = int(p.size)
    if m == 0:
        return []
    order = np.argsort(p, kind="mergesort")
    adj = np.empty(m, dtype=np.float64)
    running = 0.0
    for rank, idx in enumerate(order):
        scaled = min(1.0, (m - rank) * float(p[idx]))
        running = max(running, scaled)
        adj[idx] = running
    return [float(v) for v in adj]


def _iqr(x: FloatArray) -> list[float]:
    """Inclusive 25th and 75th percentiles."""
    lo, hi = np.percentile(x, [25.0, 75.0])
    return [float(lo), float(hi)]


def compare(  # noqa: PLR0913 - matches docs/12 §3.5 / docs/19 §5 compare payload
    metric_by_strategy: Mapping[str, Sequence[float]],
    *,
    metric: str,
    reference: str = _DEFAULT_REFERENCE,
    n_resamples: int = _DEFAULT_RESAMPLES,
    alpha: float = _DEFAULT_ALPHA,
    rng: np.random.Generator | None = None,
    higher_is_better: bool = True,
) -> dict[str, object]:
    """Build the ``ExperimentComparison`` payload for one metric (docs/12 §3.5).

    Pairwise tests are ``reference`` vs each other strategy; Holm is applied over
    those pairs. A12 is P(reference beats other): ``P(ref > other)`` when
    ``higher_is_better``, else ``P(ref < other)``.

    Args:
        metric_by_strategy: Observed metric values per strategy (one entry per seed).
        metric: Metric id (e.g. ``MET-03``).
        reference: Reference strategy id (default ``S-PROBE``).
        n_resamples: Bootstrap resamples for median CIs.
        alpha: Significance level and CI tail mass.
        rng: Injected generator for bootstrap.
        higher_is_better: Direction of "beats" for A12.

    Returns:
        Dict with ``experiment_id`` left to the caller, plus ``metrics``,
        ``strategies``, and ``tests``.
    """
    generator = np.random.default_rng() if rng is None else rng
    strategies: dict[str, dict[str, MetricSummary]] = {}
    for name, values in metric_by_strategy.items():
        xx = _as_float_array(values)
        median = float(np.median(xx)) if xx.size else float("nan")
        iqr = _iqr(xx) if xx.size else [float("nan"), float("nan")]
        ci = bootstrap_ci(xx, lambda s: float(np.median(s)), n_resamples, alpha, generator)
        strategies[name] = {
            metric: MetricSummary(median=median, iqr=iqr, ci95=[ci[0], ci[1]]),
        }

    others = [name for name in metric_by_strategy if name != reference]
    raw_p: list[float] = []
    rows: list[dict[str, str | float]] = []
    ref_vals = metric_by_strategy.get(reference, ())
    for other in others:
        other_vals = metric_by_strategy[other]
        _u, p_raw = mann_whitney_u(ref_vals, other_vals)
        a12_val = a12(ref_vals, other_vals) if higher_is_better else a12(other_vals, ref_vals)
        raw_p.append(p_raw)
        rows.append(
            {
                "metric": metric,
                "a": reference,
                "b": other,
                "test": _MWU_NAME,
                "p": p_raw,
                "a12": a12_val,
                "effect": effect_label(a12_val),
            }
        )
    adjusted = holm(raw_p)
    tests: list[PairwiseTest] = []
    for row, p_h in zip(rows, adjusted, strict=True):
        tests.append(PairwiseTest(**row, p_holm=p_h))
    return {
        "metrics": [metric],
        "strategies": strategies,
        "tests": tests,
    }
