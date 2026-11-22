"""Failure mode routes (docs/12 §2).

Implements: T-082
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse

from roboprobe.api.concurrency import assert_if_match, format_etag
from roboprobe.api.deps import get_services, get_uow
from roboprobe.api.mapping import failure_mode_out
from roboprobe.api.pagination import Page
from roboprobe.api.schemas import FailureModeOut, FailureModePatch
from roboprobe.core.errors import NotFoundError, ValidationError

__all__ = ["router"]

router = APIRouter(tags=["modes"])


def _is_provisional(analysis: Any) -> bool:
    summary = getattr(analysis, "summary", None) or {}
    clustering = summary.get("clustering")
    return isinstance(clustering, dict) and clustering.get("provisional") is True


def _first_seen_ordinal(uow: Any, mode: Any) -> int | None:
    run_id = getattr(mode, "first_seen_run", None)
    run = uow.runs.get(run_id) if run_id is not None else None
    return None if run is None else int(run.ordinal)


@router.get("/campaigns/{campaign_id}/modes")
def list_modes(campaign_id: UUID, uow: Any = Depends(get_uow)) -> Page[FailureModeOut]:
    if uow.campaigns.get(campaign_id) is None:
        msg = "campaign not found"
        raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
    modes = uow.modes.list_for_campaign(campaign_id)
    provisional = {
        row.id: _is_provisional(row) for row in uow.analyses.list_for_campaign(campaign_id)
    }
    return Page(
        items=[
            failure_mode_out(
                m,
                provisional=provisional.get(getattr(m, "analysis_id", None), False),
                first_seen_ordinal=_first_seen_ordinal(uow, m),
            )
            for m in modes
        ]
    )


@router.get("/modes/{mode_id}")
def get_mode(mode_id: UUID, response: Response, uow: Any = Depends(get_uow)) -> FailureModeOut:
    row = uow.modes.get(mode_id)
    if row is None:
        msg = "failure mode not found"
        raise NotFoundError(msg, context={"mode_id": str(mode_id)})
    response.headers["ETag"] = format_etag(getattr(row, "etag_version", 1))
    analysis_id = getattr(row, "analysis_id", None)
    analysis = uow.analyses.get(analysis_id) if analysis_id is not None else None
    return failure_mode_out(
        row, provisional=_is_provisional(analysis), first_seen_ordinal=_first_seen_ordinal(uow, row)
    )


@router.patch("/modes/{mode_id}", response_model=FailureModeOut)
def patch_mode(
    mode_id: UUID,
    body: FailureModePatch,
    if_match: str | None = Header(default=None, alias="If-Match"),
    uow: Any = Depends(get_uow),
) -> JSONResponse:
    row = uow.modes.get(mode_id)
    if row is None:
        msg = "failure mode not found"
        raise NotFoundError(msg, context={"mode_id": str(mode_id)})
    etag = getattr(row, "etag_version", 1)
    assert_if_match(if_match, int(etag))
    if body.duplicate_of:
        codes = {
            mode.code for mode in uow.modes.list_for_campaign(row.campaign_id) if mode.id != mode_id
        }
        if body.duplicate_of not in codes:
            msg = "duplicate_of must name a different mode in this campaign"
            raise ValidationError(msg)
    uow.modes.patch(
        mode_id,
        label=body.label,
        status=body.status,
        duplicate_of=body.duplicate_of,
        expected_etag=int(etag),
    )
    uow.events.append(
        "campaign.updated", {"campaign_id": str(row.campaign_id)}, campaign_id=row.campaign_id
    )
    uow.commit()
    updated = uow.modes.get(mode_id)
    if updated is None:
        msg = "failure mode not found"
        raise NotFoundError(msg, context={"mode_id": str(mode_id)})
    analysis_id = getattr(updated, "analysis_id", None)
    analysis = uow.analyses.get(analysis_id) if analysis_id is not None else None
    payload = failure_mode_out(
        updated,
        provisional=_is_provisional(analysis),
        first_seen_ordinal=_first_seen_ordinal(uow, updated),
    )
    return JSONResponse(
        content=payload.model_dump(mode="json"),
        headers={"ETag": format_etag(int(etag) + 1)},
    )


@router.post("/modes/{mode_id}:confirm-interaction", status_code=202)
def confirm_interaction(
    mode_id: UUID, request: Request, uow: Any = Depends(get_uow)
) -> dict[str, Any]:
    """Enqueue the actual idempotent confirmation plan instead of acknowledging a no-op."""
    mode = uow.modes.get(mode_id)
    if mode is None:
        msg = "failure mode not found"
        raise NotFoundError(msg, context={"mode_id": str(mode_id)})
    service = getattr(get_services(request), "confirmations", None)
    if service is None:
        msg = "confirmation service is unavailable"
        raise ValidationError(msg)
    return {"run_ids": [str(rid) for rid in service.request(mode.campaign_id, mode_id)]}
