"""Failure mode routes (docs/12 §2).

Implements: T-082
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse

from roboprobe.api.concurrency import assert_if_match, format_etag
from roboprobe.api.deps import get_uow
from roboprobe.api.mapping import failure_mode_out
from roboprobe.api.pagination import Page
from roboprobe.api.schemas import FailureModeOut, FailureModePatch
from roboprobe.core.errors import NotFoundError

__all__ = ["router"]

router = APIRouter(tags=["modes"])


@router.get("/campaigns/{campaign_id}/modes")
def list_modes(campaign_id: UUID, uow: Any = Depends(get_uow)) -> Page[FailureModeOut]:
    if uow.campaigns.get(campaign_id) is None:
        msg = "campaign not found"
        raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
    modes = uow.modes.list_for_campaign(campaign_id)
    return Page(items=[failure_mode_out(m) for m in modes])


@router.get("/modes/{mode_id}")
def get_mode(mode_id: UUID, uow: Any = Depends(get_uow)) -> FailureModeOut:
    row = uow.modes.get(mode_id)
    if row is None:
        msg = "failure mode not found"
        raise NotFoundError(msg, context={"mode_id": str(mode_id)})
    return failure_mode_out(row)


@router.patch("/modes/{mode_id}")
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
    uow.modes.patch(mode_id, label=body.label, status=body.status)
    uow.commit()
    updated = uow.modes.get(mode_id)
    if updated is None:
        msg = "failure mode not found"
        raise NotFoundError(msg, context={"mode_id": str(mode_id)})
    payload = failure_mode_out(updated)
    return JSONResponse(
        content=payload.model_dump(mode="json"),
        headers={"ETag": format_etag(int(etag) + 1)},
    )


@router.post("/modes/{mode_id}:confirm-interaction", status_code=202)
def confirm_interaction(mode_id: UUID, uow: Any = Depends(get_uow)) -> dict[str, str]:
    if uow.modes.get(mode_id) is None:
        msg = "failure mode not found"
        raise NotFoundError(msg, context={"mode_id": str(mode_id)})
    return {"mode_id": str(mode_id), "status": "accepted"}
