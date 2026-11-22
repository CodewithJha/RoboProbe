"""Empirical experiment chart evidence from recorded runs and mode memberships.

Implements: T-112b, FR-DSH-006, FR-EXP-003
"""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from uuid import UUID

import numpy as np

from roboprobe.core.seeding import ANALYSIS, derive_seed
from roboprobe.core.settings.experiments import ExperimentSettings
from roboprobe.core.types import Verdict
from roboprobe.metrics.campaign_metrics import (
    CampaignRun,
    FirstFailure,
    failure_discovery_rate,
    first_failure,
    is_comparison_run,
)
from roboprobe.metrics.survival import kaplan_meier

__all__ = [
    "ChartCell",
    "ChartRun",
    "DiscoveryPoint",
    "StrategyCharts",
    "SurvivalPoint",
    "chart_groups",
]


@dataclass(frozen=True, slots=True)
class ChartRun:
    """An adjudicated episode and its position in production proposal order."""

    id: UUID
    ordinal: int
    repeat_index: int
    outcome: CampaignRun


@dataclass(frozen=True, slots=True)
class ChartCell:
    """A completed experimental cell and, when available, final-analysis members."""

    strategy: str
    runs: Sequence[ChartRun]
    mode_members: Mapping[UUID, Sequence[UUID]] | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryPoint:
    """Pointwise median cumulative modes with a percentile-bootstrap interval."""

    simulations: int
    median: float
    low: float | None
    high: float | None


@dataclass(frozen=True, slots=True)
class SurvivalPoint:
    """Kaplan-Meier survival after failures at this time, and number censored here."""

    simulations: int
    probability: float
    censored: int


@dataclass(frozen=True, slots=True)
class StrategyCharts:
    """Per-strategy samples and discovery/survival estimates."""

    strategy: str
    observed_cells: int
    analyzed_cells: int
    metric_samples: dict[str, list[float]]
    discovery: list[DiscoveryPoint]
    survival: list[SurvivalPoint]


@dataclass(frozen=True, slots=True)
class _ObservedCell:
    outcomes: tuple[CampaignRun, ...]
    first_modes: tuple[int, ...] | None


def _observe(cell: ChartCell) -> _ObservedCell:
    runs = sorted(
        (run for run in cell.runs if is_comparison_run(run.outcome)),
        key=lambda run: (run.ordinal, run.repeat_index, run.id),
    )
    first_modes: tuple[int, ...] | None = None
    if cell.mode_members is not None:
        failing_positions = {
            row.id: position
            for position, row in enumerate(runs, start=1)
            if row.outcome.verdict is Verdict.FAIL
        }
        first_seen: list[int] = []
        for members in cell.mode_members.values():
            positions = [
                failing_positions[member] for member in members if member in failing_positions
            ]
            if positions:
                first_seen.append(min(positions))
        first_modes = tuple(sorted(first_seen))
    return _ObservedCell(tuple(run.outcome for run in runs), first_modes)


def _discovery(
    cells: Sequence[tuple[int, ...]],
    horizon: int,
    *,
    settings: ExperimentSettings,
    rng: np.random.Generator,
) -> list[DiscoveryPoint]:
    if not cells:
        return []
    moments = sorted({0, horizon, *(n for first in cells for n in first if n <= horizon)})
    sampled = (
        rng.integers(len(cells), size=(settings.bootstrap_resamples, len(cells)))
        if len(cells) > 1
        else None
    )
    bounds = (settings.alpha / 2, 1 - settings.alpha / 2)
    points = []
    for time in moments:
        values = np.asarray([bisect_right(first, time) for first in cells], dtype=np.float64)
        low = high = None
        if sampled is not None:
            medians = np.median(values[sampled], axis=1)
            endpoints = np.quantile(medians, bounds)
            low, high = float(endpoints[0]), float(endpoints[1])
        points.append(DiscoveryPoint(time, float(np.median(values)), low, high))
    return points


def _survival(observations: Sequence[FirstFailure]) -> list[SurvivalPoint]:
    times = [float(entry.n1) for entry in observations]
    events = [not entry.censored for entry in observations]
    event_times, probabilities = kaplan_meier(times, events)
    censor_counts = Counter(entry.n1 for entry in observations if entry.censored)
    by_time = {int(t): float(s) for t, s in zip(event_times, probabilities, strict=True)}
    points = []
    level = 1.0
    for time in sorted(by_time.keys() | censor_counts.keys()):
        level = by_time.get(time, level)
        points.append(SurvivalPoint(time, level, censor_counts[time]))
    return points


def chart_groups(
    cells: Sequence[ChartCell],
    *,
    metrics: Sequence[str],
    settings: ExperimentSettings,
    seed: int,
) -> list[StrategyCharts]:
    """Aggregate genuine per-cell observations and right-censor at the last observed run.

    Discovery points end at the longest horizon observed in every analyzed cell.
    A single analyzed cell yields a curve without a confidence band.
    """
    groups: dict[str, list[_ObservedCell]] = defaultdict(list)
    observed = [(cell.strategy, _observe(cell)) for cell in cells]
    for strategy, observation in observed:
        if observation.outcomes:
            groups[strategy].append(observation)
    horizon = min(
        (
            len(cell.outcomes)
            for group in groups.values()
            for cell in group
            if cell.first_modes is not None
        ),
        default=0,
    )

    series = []
    for label, group in sorted(groups.items()):
        analyzed = [cell.first_modes for cell in group if cell.first_modes is not None]
        rng = np.random.default_rng(derive_seed(seed, ANALYSIS, "comparison-chart", label))
        fdr = [failure_discovery_rate(cell.outcomes)[0] for cell in group]
        failures = [first_failure(cell.outcomes) for cell in group]
        samples = {
            "MET-01": [value for value in fdr if isfinite(value)],
            "MET-03": [float(item.n1) for item in failures if not item.censored],
        }
        series.append(
            StrategyCharts(
                strategy=label,
                observed_cells=len(group),
                analyzed_cells=len(analyzed),
                metric_samples={metric: samples[metric] for metric in metrics if metric in samples},
                discovery=_discovery(analyzed, horizon, settings=settings, rng=rng),
                survival=_survival(failures) if "MET-03" in metrics else [],
            )
        )
    return series
