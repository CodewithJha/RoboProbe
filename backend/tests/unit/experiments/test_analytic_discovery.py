"""Ground-truth comparison metrics for the EXP-02 multi-mode benchmark."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import numpy as np
import pyarrow.parquet as pq
import pytest

from roboprobe.core.errors import ValidationError
from roboprobe.core.settings.experiments import ExperimentSettings
from roboprobe.core.types import CampaignStatus, Verdict
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
