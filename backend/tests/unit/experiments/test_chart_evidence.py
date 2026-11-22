"""Check empirical T-112b chart inputs and censoring."""

from __future__ import annotations

from uuid import UUID

import pytest

from roboprobe.core.settings.experiments import ExperimentSettings
from roboprobe.core.types import Verdict
from roboprobe.experiments.chart_evidence import ChartCell, ChartRun, chart_groups
from roboprobe.metrics.campaign_metrics import CampaignRun

pytestmark = pytest.mark.unit


def run(
    identifier: int,
    ordinal: int,
    verdict: Verdict,
    *,
    repeat: int = 0,
    tags: tuple[str, ...] = (),
) -> ChartRun:
    return ChartRun(
        UUID(int=identifier),
        ordinal,
        repeat,
        CampaignRun(verdict=verdict, wall_time_s=0.0, tags=tags),
    )


def test_chart_evidence_counts_distinct_mode_members_and_censors_observed_times() -> None:
    replay = run(1, 0, Verdict.FAIL, tags=("confirm",))
    passing = run(2, 1, Verdict.PASS)
    first = run(3, 2, Verdict.FAIL)
    repeated = run(4, 2, Verdict.FAIL, repeat=1)
    second = run(5, 3, Verdict.FAIL)
    invalid = run(6, 4, Verdict.INVALID)
    memberships = {
        UUID(int=101): [replay.id, repeated.id, first.id],
        UUID(int=102): [second.id],
    }
    cells = [
        ChartCell("Probe", [second, repeated, invalid, first, passing, replay], memberships),
        ChartCell("Probe", [run(i, i, Verdict.PASS) for i in range(3)], {}),
        ChartCell("Random", [run(7, 1, Verdict.INVALID)]),
    ]
    settings = ExperimentSettings(bootstrap_resamples=128)
    result = chart_groups(cells, metrics=["MET-01", "MET-03"], settings=settings, seed=42)
    probe, random = result
    assert probe.strategy == "Probe"
    assert probe.metric_samples == {"MET-01": [0.75, 0.0], "MET-03": [2.0]}
    assert probe.observed_cells == probe.analyzed_cells == 2
    assert [(point.simulations, point.median) for point in probe.discovery] == [
        (0, 0.0),
        (2, 0.5),
        (3, 0.5),
    ]
    assert (probe.discovery[1].low, probe.discovery[1].high) == (0.0, 1.0)
    assert [(p.simulations, p.probability, p.censored) for p in probe.survival] == [
        (0, 1.0, 0),
        (2, 0.5, 0),
        (3, 0.5, 1),
    ]
    assert random.strategy == "Random"
    assert random.metric_samples == {"MET-01": [], "MET-03": []}
    assert not random.discovery
    assert random.survival[-1].simulations == 1
    assert random.survival[-1].censored == 1
    assert result == chart_groups(cells, metrics=["MET-01", "MET-03"], settings=settings, seed=42)


def test_single_analyzed_cell_has_no_confidence_band() -> None:
    fail = run(1, 0, Verdict.FAIL)
    (group,) = chart_groups(
        [ChartCell("Probe", [fail], {UUID(int=100): [fail.id]})],
        metrics=["MET-01"],
        settings=ExperimentSettings(),
        seed=0,
    )
    assert [point.median for point in group.discovery] == [0, 1]
    assert all(point.low is None and point.high is None for point in group.discovery)
    assert not group.survival
