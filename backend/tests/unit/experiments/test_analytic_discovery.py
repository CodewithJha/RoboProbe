"""Ground-truth comparison metrics for the EXP-02 benchmarks."""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import numpy as np
import pyarrow.parquet as pq
import pytest

from roboprobe.core.errors import ValidationError
from roboprobe.core.settings.experiments import ExperimentSettings
from roboprobe.core.types import CampaignStatus, Verdict
from roboprobe.experiments.comparison import resolve_comparison
from roboprobe.experiments.runner import _CampaignRow, build_comparison, export_raw_parquet
from roboprobe.metrics.campaign_metrics import CampaignRun
from roboprobe.selection.benchmarks import MODE_CANONICAL, NOMINAL_POINT

pytestmark = pytest.mark.unit


def test_analytic_comparison_counts_each_verified_ground_truth_mode_once(tmp_path: Path) -> None:
    campaign = _CampaignRow(UUID(int=1), "S-PROBE", "S-PROBE", 6, CampaignStatus.COMPLETED, 0)
    runs = [
        CampaignRun(Verdict.PASS, 1.0, MODE_CANONICAL["B"]),
        CampaignRun(Verdict.FAIL, 1.0, MODE_CANONICAL["A"]),
        CampaignRun(Verdict.FAIL, 1.0, MODE_CANONICAL["A"]),
        CampaignRun(Verdict.FAIL, 1.0, NOMINAL_POINT),
        CampaignRun(Verdict.FAIL, 1.0, MODE_CANONICAL["B"]),
        CampaignRun(Verdict.FAIL, 1.0, MODE_CANONICAL["C"], phase="confirm"),
    ]
    comparison = build_comparison(
        UUID(int=2),
        [campaign],
        {campaign.id: runs},
        metrics=("MET-02", "MET-09"),
        settings=ExperimentSettings(bootstrap_resamples=8),
        rng=np.random.default_rng(0),
        analytic_multimode=True,
    )
    scores = comparison["strategies"]["S-PROBE"]
    assert scores["MET-02"]["median"] == 2.0
    assert scores["MET-09"]["median"] == pytest.approx(7 / 24)

    raw = tmp_path / "observations.parquet"
    export_raw_parquet(raw, [campaign], {campaign.id: runs})
    table = pq.read_table(raw)
    assert table.column("x_unit").to_pylist()[1] == list(MODE_CANONICAL["A"])
    assert table.column("is_comparison_run").to_pylist() == [True] * 5 + [False]


def test_branin_comparison_counts_three_noise_free_modes_in_proposal_order() -> None:
    campaign = _CampaignRow(UUID(int=1), "S-PROBE", "S-PROBE", 7, CampaignStatus.COMPLETED, 0)
    left = ((5.0 - math.pi) / 15.0, 12.275 / 15.0)
    middle = ((5.0 + math.pi) / 15.0, 2.275 / 15.0)
    right = ((5.0 + 3.0 * math.pi) / 15.0, 2.475 / 15.0)
    runs = [
        CampaignRun(Verdict.PASS, 1.0, right),
        CampaignRun(Verdict.FAIL, 1.0, left),
        CampaignRun(Verdict.FAIL, 1.0, left),
        CampaignRun(Verdict.FAIL, 1.0, (5.0 / 15.0, 0.4)),
        CampaignRun(Verdict.FAIL, 1.0, right),
        CampaignRun(Verdict.FAIL, 1.0, middle, phase="confirm"),
        CampaignRun(Verdict.FAIL, 1.0, middle),
    ]
    exp = SimpleNamespace(
        design={
            "backend": "benchmark",
            "space": {"id": "branin_2d"},
            "metrics": ["MET-01", "MET-02", "MET-09"],
        },
        results=None,
    )
    comparison = resolve_comparison(
        UUID(int=2), exp, [campaign], {campaign.id: runs}, ExperimentSettings(bootstrap_resamples=8)
    )
    scores = comparison["strategies"]["S-PROBE"]
    assert scores["MET-01"]["median"] == pytest.approx(5 / 6)
    assert scores["MET-02"]["median"] == 3.0
    assert scores["MET-09"]["median"] == pytest.approx(11 / 21)


def test_discovery_refuses_comparison_without_known_mode_evidence() -> None:
    campaign = _CampaignRow(UUID(int=1), "S-PROBE", "S-PROBE", 6, CampaignStatus.COMPLETED, 0)
    with pytest.raises(ValidationError, match="unsupported experiment metric MET-02"):
        build_comparison(
            UUID(int=2),
            [campaign],
            {campaign.id: []},
            metrics=("MET-02",),
            settings=ExperimentSettings(),
            rng=np.random.default_rng(0),
        )
