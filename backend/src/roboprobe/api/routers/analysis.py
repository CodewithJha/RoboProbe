"""Importance and risk summary routes (docs/12 §2).

Implements: T-082
"""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from roboprobe.api.artifact_ref import artifact_ref_from_record
from roboprobe.api.deps import get_services, get_uow
from roboprobe.api.mapping import risk_out
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
    if risk is None:
        return RiskOut(campaign_id=campaign_id)
    return risk_out(risk, campaign_id=campaign_id)


@router.get("/campaigns/{campaign_id}/risk/slice")
def risk_slice(  # noqa: PLR0913, PLR0917
    campaign_id: UUID,
    request: Request,
    x: str,
    y: str,
    anchor: str = "nominal",
    resolution: int = 50,
    uow: Any = Depends(get_uow),
) -> RiskSliceOut:
    settings: RoboProbeSettings = request.app.state.settings
    max_res = settings.risk.slice_resolution
    if resolution < 1 or resolution > max_res:
        msg = f"resolution must be in 1..{max_res}"
        raise ValidationError(msg, context={"resolution": resolution})
    risk = uow.risk_maps.latest(campaign_id)
    if risk is None or risk.slices_artifact is None:
        msg = "risk slice data not available"
        raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
    art = uow.artifacts.get(risk.slices_artifact)
    if art is None:
        msg = "slice artifact missing"
        raise NotFoundError(msg)
    store = get_services(request).artifact_store
    raw = cast(Any, store.open(artifact_ref_from_record(art))).read()
    slices = json.loads(raw.decode("utf-8"))
    selected = None
    for item in slices if isinstance(slices, list) else []:
        if item.get("x_param") == x and item.get("y_param") == y:
            selected = item
            break
    if selected is None:
        msg = "requested slice not found"
        raise NotFoundError(msg, context={"x_param": x, "y_param": y})
    grid = selected if isinstance(selected, dict) else {}
    extras = {
        key: grid[key]
        for key in (
            "log_x",
            "log_y",
            "x_values",
            "y_values",
            "p_fail",
            "points",
            "region",
        )
        if key in grid
    }
    return RiskSliceOut(
        x_param=x,
        y_param=y,
        anchor=anchor,
        resolution=resolution,
        grid=grid,
        **extras,
    )
