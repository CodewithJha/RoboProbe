"""Comparison chart evidence from completed experimental cells (T-112b)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from roboprobe.api.deps import get_settings, get_uow
from roboprobe.core.errors import NotFoundError
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import CampaignStatus, Verdict
from roboprobe.experiments.chart_evidence import ChartCell, ChartRun, StrategyCharts, chart_groups
from roboprobe.experiments.planner import ExperimentDesign
from roboprobe.experiments.runner import _as_campaign_row
from roboprobe.metrics.campaign_metrics import CampaignRun

__all__ = ["router"]

router = APIRouter(prefix="/experiments", tags=["experiments"])


class ExperimentChartsOut(BaseModel):
    """Per-strategy evidence prepared from stored runs and final mode analysis."""

    model_config = ConfigDict(extra="forbid")

    experiment_id: UUID
    metrics: list[str]
    confidence: float
    excluded_cells: int
    groups: list[StrategyCharts]


def _chart_runs(uow: Any, campaign_id: UUID) -> list[ChartRun]:
    runs: list[ChartRun] = []
    cursor: str | None = None
    while True:
        page = uow.runs.list_for_campaign(campaign_id, cursor=cursor)
        for row in page.items:
            if row.verdict is not None:
                runs.append(
                    ChartRun(
                        id=row.id,
                        ordinal=row.ordinal,
                        repeat_index=row.repeat_index,
                        outcome=CampaignRun(
                            verdict=Verdict(row.verdict),
                            wall_time_s=0.0,
                            phase=str(row.phase or ""),
                            tags=tuple(str(tag) for tag in row.tags),
                        ),
                    )
                )
        cursor = page.next_cursor
        if cursor is None:
            return runs


def _mode_members(
    uow: Any,
    campaign_id: UUID,
    run_count: int,
) -> dict[UUID, Sequence[UUID]] | None:
    analyses = uow.analyses.list_for_campaign(campaign_id)
    final = next((item for item in reversed(analyses) if item.kind == "final"), None)
    if final is None or final.status != "DONE" or final.n_runs != run_count:
        return None
    members = cast(
        "dict[UUID, Sequence[UUID]]",
        uow.modes.member_run_ids_for_analysis(campaign_id, final.id),
    )
    expected = (final.summary or {}).get("n_modes")
    if (expected is not None and len(members) != expected) or not all(members.values()):
        return None
    if not members and expected != 0:
        return None
    return members


@router.get("/{experiment_id}/comparison/charts")
def experiment_charts(
    experiment_id: UUID,
    settings: RoboProbeSettings = Depends(get_settings),
    uow: Any = Depends(get_uow),
) -> ExperimentChartsOut:
    """Read chart evidence with explicit censoring and no extrapolated runs."""
    experiment = uow.experiments.get(experiment_id)
    if experiment is None:
        msg = "experiment not found"
        raise NotFoundError(msg, context={"experiment_id": str(experiment_id)})
    design = ExperimentDesign.model_validate(experiment.design)
    metrics = list(design.metrics or ("MET-01", "MET-03"))
    campaigns = uow.campaigns.list_for_experiment(experiment_id)
    cells = []
    for record in campaigns:
        campaign = _as_campaign_row(record)
        if campaign.status is CampaignStatus.COMPLETED:
            runs = _chart_runs(uow, campaign.id)
            cells.append(
                ChartCell(
                    campaign.strategy_label,
                    runs,
                    _mode_members(uow, campaign.id, len(runs)),
                )
            )
    groups = chart_groups(
        cells, metrics=metrics, settings=settings.experiments, seed=design.seeds.root
    )
    return ExperimentChartsOut(
        experiment_id=experiment_id,
        metrics=metrics,
        confidence=1 - settings.experiments.alpha,
        excluded_cells=len(campaigns) - sum(group.observed_cells for group in groups),
        groups=groups,
    )
