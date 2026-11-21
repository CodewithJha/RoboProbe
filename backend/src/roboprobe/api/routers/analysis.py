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
from roboprobe.api.risk_queries import RiskQueries
from roboprobe.api.schemas import ImportanceOut, RiskOut, RiskSliceOut
from roboprobe.core.errors import NotFoundError, ValidationError

__all__ = ["router"]

router = APIRouter(tags=["analysis"])


def _latest_analysis(uow: Any, campaign_id: UUID) -> Any | None:
    rows = uow.analyses.list_for_campaign(campaign_id)
    full = [
        row
        for row in rows
        if str(row.kind).lower() in {"full", "final", "manual"}
        and str(row.status).upper() in {"OK", "DONE", "PARTIAL"}
    ]
    return full[-1] if full else None


@router.get("/campaigns/{campaign_id}/importance")
def campaign_importance(campaign_id: UUID, uow: Any = Depends(get_uow)) -> ImportanceOut:
    if uow.campaigns.get(campaign_id) is None:
        msg = "campaign not found"
        raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
    analysis = _latest_analysis(uow, campaign_id)
    if analysis is None:
        msg = "Run analysis first; no completed full analysis is available"
        raise NotFoundError(msg)
    summary = {} if analysis.summary is None else dict(analysis.summary)
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
    if risk is None:
        return RiskOut(campaign_id=campaign_id)
    return risk_out(risk, campaign_id=campaign_id)


@router.get("/campaigns/{campaign_id}/risk/slice")
async def risk_slice(  # noqa: PLR0913, PLR0917 - documented slice options
    campaign_id: UUID,
    request: Request,
    x: str,
    y: str,
    anchor: str = "nominal",
    resolution: int | None = None,
) -> RiskSliceOut:
    """Compute in a worker thread with a deadline; cached slices track analysis versions."""
    settings = request.app.state.settings
    size = settings.risk.slice_resolution if resolution is None else resolution
    if size < 10 or size > settings.risk.max_slice_resolution or x == y:
        msg = "invalid slice axes or resolution"
        raise ValidationError(msg)
    state = request.app.state
    if not hasattr(state, "risk_queries"):
        state.risk_queries = RiskQueries(get_services(request))
        state.risk_lock = asyncio.Lock()
    try:
        async with state.risk_lock:
            payload = await asyncio.wait_for(
                run_in_threadpool(state.risk_queries.slice, campaign_id, x, y, anchor, size),
                timeout=settings.api.slice_timeout_s,
            )
    except TimeoutError as exc:
        raise HTTPException(status_code=503, detail="risk slice computation timed out") from exc
    return RiskSliceOut.model_validate(payload)
