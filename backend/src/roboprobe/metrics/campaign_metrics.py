"""Per-campaign counting metrics MET-01, MET-03, MET-05, MET-06, MET-07.

Pure functions over proposal-order runs. Confirm-tagged / ``confirm``-phase runs
are excluded from strategy comparison (docs/09 §6).

Implements: FR-EXP-001, MET-01, MET-03, MET-05, MET-06, MET-07
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from roboprobe.core.settings.experiments import ExperimentSettings
from roboprobe.core.types import FailureClass, Verdict
from roboprobe.metrics.statistics import bootstrap_ci

__all__ = [
    "CampaignRun",
    "FirstFailure",
    "Replay",
    "cost_per_mode",
    "failure_discovery_rate",
    "first_failure",
    "is_comparison_run",
    "reproducibility",
    "robustness_delta",
    "robustness_score",
]

type FloatArray = npt.NDArray[np.float64]
SECONDS_PER_HOUR = 3600.0
"""SI conversion used by FDR_h (docs/19 §3 MET-01)."""
UNCERTAIN_WEIGHT = 0.5
"""Weight of the UNCERTAIN volume in the robustness score (docs/09 §5.4)."""
CONFIRM = "confirm"
REGION_SAFE = "SAFE"
REGION_UNCERTAIN = "UNCERTAIN"
REGION_FAILURE = "FAILURE"

_EXPERIMENT = ExperimentSettings()
_DEFAULT_RESAMPLES = _EXPERIMENT.bootstrap_resamples
_DEFAULT_ALPHA = _EXPERIMENT.alpha


@dataclass(frozen=True, slots=True)
class CampaignRun:
    """One campaign episode in proposal order (docs/19 §2).

    Attributes:
        verdict: Judged verdict.
        wall_time_s: Wall time of the episode (seconds).
        x_unit: Normalised scenario in the unit cube (optional for counting metrics).
        phase: Selection phase; ``confirm`` is excluded from comparison metrics.
        tags: Free tags; a ``confirm`` tag is excluded from comparison metrics.
        failure_class: Primary failure class, if any.
    """

    verdict: Verdict
    wall_time_s: float
    x_unit: tuple[float, ...] = ()
    phase: str = ""
    tags: tuple[str, ...] = ()
    failure_class: FailureClass | None = None


@dataclass(frozen=True, slots=True)
class FirstFailure:
    """MET-03: sims to first failure, with a right-censoring flag (docs/19 §3)."""

    n1: int
    censored: bool


@dataclass(frozen=True, slots=True)
class Replay:
    """One replay of a mode medoid (MET-06)."""

    verdict: Verdict
    failure_class: FailureClass | None = None


def is_comparison_run(run: CampaignRun) -> bool:
    """Return whether ``run`` counts in strategy-comparison metrics (docs/09 §6)."""
    return run.phase != CONFIRM and CONFIRM not in run.tags


def comparison_runs(runs: Sequence[CampaignRun]) -> tuple[CampaignRun, ...]:
    """Proposal-order runs excluding confirmatory interaction tests."""
    return tuple(run for run in runs if is_comparison_run(run))


def _valid(runs: Sequence[CampaignRun]) -> tuple[CampaignRun, ...]:
    return tuple(run for run in runs if run.verdict is not Verdict.INVALID)


def _failing(runs: Sequence[CampaignRun]) -> tuple[CampaignRun, ...]:
    return tuple(run for run in runs if run.verdict is Verdict.FAIL)


def failure_discovery_rate(runs: Sequence[CampaignRun]) -> tuple[float, float]:
    """MET-01: ``FDR = |F|/|V|`` and ``FDR_h = |F| / (Σ t_i / 3600)``.

    ``V`` is valid (non-INVALID) comparison runs; ``F ⊆ V`` are FAIL runs.
    ``Σ t_i`` is wall time of all comparison runs (CPU spent, including INVALID).
    Empty ``V`` → FDR is ``nan``. Zero total time → FDR_h is ``nan``.

    Implements: MET-01 (docs/19 §3).
    """
    cmp_runs = comparison_runs(runs)
    valid = _valid(cmp_runs)
    n_fail = len(_failing(cmp_runs))
    n_valid = len(valid)
    fdr = n_fail / n_valid if n_valid else float("nan")
    total_s = sum(run.wall_time_s for run in cmp_runs)
    fdr_h = n_fail / (total_s / SECONDS_PER_HOUR) if total_s > 0.0 else float("nan")
    return fdr, fdr_h


def first_failure(runs: Sequence[CampaignRun], budget: int | None = None) -> FirstFailure:
    """MET-03: 1-based index of the first FAIL among comparison runs.

    If none fail, the value is right-censored at ``B`` (budget; default =
    number of comparison runs). Mann-Whitney comparisons should treat censored
    values as ``B + 1`` (docs/19 §3).

    Implements: MET-03.
    """
    cmp_runs = comparison_runs(runs)
    b = len(cmp_runs) if budget is None else budget
    for index, run in enumerate(cmp_runs, start=1):
        if run.verdict is Verdict.FAIL:
            return FirstFailure(n1=index, censored=False)
    return FirstFailure(n1=b, censored=True)


def cost_per_mode(
    runs: Sequence[CampaignRun], n_modes: int, budget: int | None = None
) -> tuple[float, float]:
    """MET-05: ``CPM = Σ t_i / MET-02`` (s) and ``SPM = B / MET-02``.

    Both are ``+inf`` when ``n_modes == 0``. ``Σ t_i`` and ``B`` use comparison
    runs (docs/19 §3).

    Implements: MET-05.
    """
    cmp_runs = comparison_runs(runs)
    b = len(cmp_runs) if budget is None else budget
    if n_modes == 0:
        return float("inf"), float("inf")
    total_s = sum(run.wall_time_s for run in cmp_runs)
    return total_s / n_modes, b / n_modes


def reproducibility(
    expected_by_mode: Mapping[str, Replay],
    replays_by_mode: Mapping[str, Sequence[Replay]],
) -> float:
    """MET-06: mean over modes of (replays matching original verdict & class) / R.

    ``R`` is the number of provided replays for that mode (docs/19 §3 uses R = 5).
    Modes with no replays are skipped. No modes → ``nan``.

    Implements: MET-06.
    """
    rates: list[float] = []
    for mode_id, expected in expected_by_mode.items():
        trials = replays_by_mode.get(mode_id, ())
        if not trials:
            continue
        matched = sum(
            trial.verdict is expected.verdict and trial.failure_class is expected.failure_class
            for trial in trials
        )
        rates.append(matched / len(trials))
    if not rates:
        return float("nan")
    return float(sum(rates) / len(rates))


def robustness_score(region_labels: Sequence[str]) -> float:
    """Volume robustness ``1 - f_FAILURE - 0.5 * f_UNCERTAIN`` (docs/09 §5.4).

    ``region_labels`` are ``SAFE`` / ``UNCERTAIN`` / ``FAILURE`` classifications
    of a space-filling sample. Empty input → ``nan``.
    """
    n = len(region_labels)
    if n == 0:
        return float("nan")
    n_fail = sum(label == REGION_FAILURE for label in region_labels)
    n_unc = sum(label == REGION_UNCERTAIN for label in region_labels)
    return 1.0 - (n_fail / n) - UNCERTAIN_WEIGHT * (n_unc / n)


def _point_scores(region_labels: Sequence[str]) -> FloatArray:
    """Per-sample contribution to :func:`robustness_score`."""
    out = np.empty(len(region_labels), dtype=np.float64)
    for i, label in enumerate(region_labels):
        if label == REGION_FAILURE:
            out[i] = 0.0
        elif label == REGION_UNCERTAIN:
            out[i] = UNCERTAIN_WEIGHT
        else:
            out[i] = 1.0
    return out


def robustness_delta(
    labels_a: Sequence[str],
    labels_b: Sequence[str],
    *,
    n_resamples: int = _DEFAULT_RESAMPLES,
    alpha: float = _DEFAULT_ALPHA,
    rng: np.random.Generator | None = None,
) -> tuple[float, tuple[float, float]]:
    """MET-07: ``delta = score(B) - score(A)`` with a paired percentile bootstrap CI.

    Samples must be the same length (common Sobol points, docs/09 §5.4). The CI
    is the bootstrap of the mean of paired per-point score differences.

    Implements: MET-07.
    """
    if len(labels_a) != len(labels_b):
        msg = "labels_a and labels_b must be the same length for paired bootstrap"
        raise ValueError(msg)
    delta = robustness_score(labels_b) - robustness_score(labels_a)
    if not labels_a:
        return delta, (float("nan"), float("nan"))
    diffs = _point_scores(labels_b) - _point_scores(labels_a)
    generator = np.random.default_rng() if rng is None else rng
    ci = bootstrap_ci(diffs, lambda s: float(np.mean(s)), n_resamples, alpha, generator)
    return float(delta), ci
