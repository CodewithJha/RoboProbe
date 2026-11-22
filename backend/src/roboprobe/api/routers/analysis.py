"""Importance and risk summary routes (docs/12 §2).

Implements: T-082
"""

from __future__ import annotations

import asyncio
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from roboprobe.api.deps import get_services, get_uow
from roboprobe.api.mapping import risk_out
from roboprobe.api.risk_queries import RiskQueries, completed_risk_analysis
from roboprobe.api.schemas import ImportanceOut, RiskOut, RiskSliceOut
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.core.settings import RoboProbeSettings

__all__ = ["router"]

router = APIRouter(tags=["analysis"])


def _latest_analysis(uow: Any, campaign_id: UUID) -> Any | None:
    rows = uow.analyses.list_for_campaign(campaign_id)
    return rows[-1] if rows else None


@router.get("/campaigns/{campaign_id}/importance")
def campaign_importance(campaign_id: UUID, uow: Any = Depends(get_uow)) -> ImportanceOut:
    if uow.campaigns.get(campaign_id) is None:
        msg = "campaign not found"
        raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
    analysis = _latest_analysis(uow, campaign_id)
    summary = {} if analysis is None or analysis.summary is None else dict(analysis.summary)
    return ImportanceOut(
        campaign_id=campaign_id,
        analysis_id=None if analysis is None else analysis.id,
        importance=cast(dict[str, object] | None, summary.get("importance")),
        interactions=cast(dict[str, object] | None, summary.get("interactions")),
        rules=list(summary.get("rules", [])),
    )


@router.get("/campaigns/{campaign_id}/risk")
def campaign_risk(campaign_id: UUID, uow: Any = Depends(get_uow)) -> RiskOut:
    if uow.campaigns.get(campaign_id) is None:
        msg = "campaign not found"
        raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
    risk = uow.risk_maps.latest(campaign_id)
    if risk is not None:
        return risk_out(risk, campaign_id=campaign_id)
    analysis = completed_risk_analysis(uow, campaign_id)
    if analysis is None:
        return RiskOut(campaign_id=campaign_id)
    volumes = analysis.summary["volumes"]
    return RiskOut(
        campaign_id=campaign_id,
        robustness_score=volumes.get("robustness_score"),
        volumes=volumes,
    )


@router.get("/campaigns/{campaign_id}/risk/slice")
async def risk_slice(  # noqa: PLR0913, PLR0917 - documented slice options
    campaign_id: UUID,
    request: Request,
    x: str,
    y: str,
    anchor: str = "nominal",
    resolution: int = 50,
    anchor_values: str | None = None,
) -> RiskSliceOut:
    """Load or compute the slice in a worker thread with a bounded deadline."""
    settings: RoboProbeSettings = request.app.state.settings
    if "resolution" not in request.query_params:
        resolution = settings.risk.slice_resolution
    if not 2 <= resolution <= settings.risk.max_slice_resolution or x == y:
        msg = "invalid slice axes or resolution"
        raise ValidationError(msg)
    state = request.app.state
    if not hasattr(state, "risk_queries"):
        state.risk_queries = RiskQueries(get_services(request))
        state.risk_lock = asyncio.Lock()
    try:
        async with state.risk_lock:
            payload = await asyncio.wait_for(
                run_in_threadpool(
                    state.risk_queries.slice, campaign_id, x, y, anchor, resolution, anchor_values
                ),
                timeout=settings.api.slice_timeout_s,
            )
    except TimeoutError as exc:
        raise HTTPException(status_code=503, detail="risk slice computation timed out") from exc
    return RiskSliceOut.model_validate(payload)
