"""Campaign CRUD and lifecycle (docs/12 §2, §5).

Implements: T-081
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.responses import JSONResponse

from roboprobe.analysis.base import AnalysisKind
from roboprobe.api.campaign_create import create_campaign
from roboprobe.api.concurrency import assert_if_match, format_etag
from roboprobe.api.deps import get_services, get_uow
from roboprobe.api.mapping import campaign_counts, campaign_out
from roboprobe.api.pagination import Page, clamp_limit
from roboprobe.api.schemas import (
    CampaignCreate,
    CampaignOut,
    CampaignPatch,
    CampaignProgress,
    ManualRunCreate,
)
from roboprobe.core.errors import ConflictError, ErrorCode, NotFoundError
from roboprobe.core.types import CampaignStatus

__all__ = ["router"]

router = APIRouter(prefix="/campaigns", tags=["campaigns"])
_TERMINAL = frozenset({CampaignStatus.COMPLETED, CampaignStatus.FAILED, CampaignStatus.CANCELLED})


def _base_path(request: Request) -> str:
    return str(request.app.state.settings.api.base_path)


def _load_runs(uow: Any, campaign_id: UUID) -> list[Any]:
    runs: list[Any] = []
    cursor: str | None = None
    while True:
        page = uow.runs.list_for_campaign(campaign_id, limit=None, cursor=cursor)
        runs.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    return runs


@router.get("")
def list_campaigns(
    request: Request,
    limit: int | None = None,
    cursor: str | None = None,
    uow: Any = Depends(get_uow),
) -> Page[CampaignOut]:
    settings = request.app.state.settings
    page = uow.campaigns.list(
        limit=clamp_limit(
            limit,
            default=settings.api.page_limit_default,
            maximum=settings.api.page_limit_max,
        ),
        cursor=cursor,
    )
    base = _base_path(request)
    items = []
    for row in page.items:
        runs = _load_runs(uow, row.id)
        counts = campaign_counts(runs, budget=row.budget)
        modes = uow.modes.list_for_campaign(row.id)
        counts["modes_found"] = len(modes)
        items.append(campaign_out(row, base_path=base, counts=counts))
    return Page(items=items, next_cursor=page.next_cursor)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_campaign_route(
    body: CampaignCreate,
    request: Request,
    uow: Any = Depends(get_uow),
) -> CampaignOut:
    services = get_services(request)
    cid = create_campaign(
        body,
        uow=uow,
        settings=services.settings,
        campaigns=services.campaigns,
        space_root=services.space_root,
    )
    uow.commit()
    row = uow.campaigns.get(cid)
    if row is None:
        msg = "campaign not found after create"
        raise NotFoundError(msg, context={"campaign_id": str(cid)})
    return campaign_out(row, base_path=_base_path(request))


@router.get("/{campaign_id}")
def get_campaign(campaign_id: UUID, request: Request, uow: Any = Depends(get_uow)) -> Response:
    row = uow.campaigns.get(campaign_id)
    if row is None:
        msg = "campaign not found"
        raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
    etag = uow.campaigns.etag_version(campaign_id)
    runs = _load_runs(uow, campaign_id)
    counts = campaign_counts(runs, budget=row.budget)
    counts["modes_found"] = len(uow.modes.list_for_campaign(campaign_id))
    payload = campaign_out(row, base_path=_base_path(request), counts=counts)
    return JSONResponse(
        content=payload.model_dump(mode="json"),
        headers={"ETag": format_etag(etag)},
    )


@router.patch("/{campaign_id}")
def patch_campaign(
    campaign_id: UUID,
    body: CampaignPatch,
    request: Request,
    if_match: str | None = Header(default=None, alias="If-Match"),
    uow: Any = Depends(get_uow),
) -> Response:
    etag = uow.campaigns.etag_version(campaign_id)
    assert_if_match(if_match, etag)
    new_etag = uow.campaigns.patch(
        campaign_id,
        name=body.name,
        tags=body.tags,
        expected_etag=etag,
    )
    uow.commit()
    row = uow.campaigns.get(campaign_id)
    if row is None:
        msg = "campaign not found"
        raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
    runs = _load_runs(uow, campaign_id)
    counts = campaign_counts(runs, budget=row.budget)
    payload = campaign_out(row, base_path=_base_path(request), counts=counts)
    return JSONResponse(
        content=payload.model_dump(mode="json"),
        headers={"ETag": format_etag(new_etag)},
    )


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(campaign_id: UUID, uow: Any = Depends(get_uow)) -> None:
    row = uow.campaigns.get(campaign_id)
    if row is None:
        msg = "campaign not found"
        raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
    status_v = (
        row.status if isinstance(row.status, CampaignStatus) else CampaignStatus(str(row.status))
    )
    if status_v not in _TERMINAL:
        msg = f"Campaign {campaign_id} is {status_v.value}; cannot delete until terminal."
        raise ConflictError(msg, code=ErrorCode.CAMPAIGN_INVALID_TRANSITION)
    uow.campaigns.delete(campaign_id)
    uow.commit()


def _command(campaign_id: UUID, request: Request, cmd: str, uow: Any) -> CampaignOut:
    services = get_services(request)
    method = getattr(services.campaigns, cmd)
    method(campaign_id)
    row = uow.campaigns.get(campaign_id)
    if row is None:
        msg = "campaign not found"
        raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
    return campaign_out(row, base_path=_base_path(request))


@router.post("/{campaign_id}:start", status_code=status.HTTP_202_ACCEPTED)
def start_campaign(campaign_id: UUID, request: Request, uow: Any = Depends(get_uow)) -> CampaignOut:
    return _command(campaign_id, request, "start", uow)


@router.post("/{campaign_id}:pause", status_code=status.HTTP_202_ACCEPTED)
def pause_campaign(campaign_id: UUID, request: Request, uow: Any = Depends(get_uow)) -> CampaignOut:
    return _command(campaign_id, request, "pause", uow)


@router.post("/{campaign_id}:resume", status_code=status.HTTP_202_ACCEPTED)
def resume_campaign(
    campaign_id: UUID, request: Request, uow: Any = Depends(get_uow)
) -> CampaignOut:
    return _command(campaign_id, request, "resume", uow)


@router.post("/{campaign_id}:cancel", status_code=status.HTTP_202_ACCEPTED)
def cancel_campaign(
    campaign_id: UUID, request: Request, uow: Any = Depends(get_uow)
) -> CampaignOut:
    return _command(campaign_id, request, "cancel", uow)


@router.post("/{campaign_id}:analyze", status_code=status.HTTP_202_ACCEPTED)
def analyze_campaign(
    campaign_id: UUID,
    request: Request,
    uow: Any = Depends(get_uow),
) -> dict[str, str]:
    if uow.campaigns.get(campaign_id) is None:
        msg = "campaign not found"
        raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
    services = get_services(request)
    services.analysis.schedule(campaign_id, AnalysisKind.FULL, complete_campaign=False)
    return {"campaign_id": str(campaign_id), "status": "scheduled"}


@router.get("/{campaign_id}/progress")
def campaign_progress(campaign_id: UUID, uow: Any = Depends(get_uow)) -> CampaignProgress:
    row = uow.campaigns.get(campaign_id)
    if row is None:
        msg = "campaign not found"
        raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
    runs = _load_runs(uow, campaign_id)
    counts = campaign_counts(runs, budget=row.budget)
    curve: list[dict[str, object]] = []
    ordinal = 0
    for run in sorted(runs, key=lambda r: r.ordinal):
        if getattr(run.verdict, "value", run.verdict) != "FAIL":
            continue
        ordinal += 1
        curve.append({"ordinal": run.ordinal, "failure_index": ordinal})
    return CampaignProgress(campaign_id=campaign_id, counts=counts, discovery_curve=curve)


@router.get("/{campaign_id}/runs")
def list_runs(
    campaign_id: UUID,
    request: Request,
    limit: int | None = None,
    cursor: str | None = None,
    uow: Any = Depends(get_uow),
) -> Page[dict[str, object]]:
    from roboprobe.api.mapping import run_out

    if uow.campaigns.get(campaign_id) is None:
        msg = "campaign not found"
        raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
    settings = request.app.state.settings
    page = uow.runs.list_for_campaign(
        campaign_id,
        limit=clamp_limit(
            limit,
            default=settings.api.page_limit_default,
            maximum=settings.api.page_limit_max,
        ),
        cursor=cursor,
    )
    items = [run_out(r).model_dump(mode="json") for r in page.items]
    return Page(items=items, next_cursor=page.next_cursor)


@router.post("/{campaign_id}/runs", status_code=status.HTTP_201_CREATED)
def add_manual_runs(
    campaign_id: UUID,
    body: ManualRunCreate,
    uow: Any = Depends(get_uow),
) -> dict[str, object]:
    from roboprobe.api._store import new_uuid, records

    campaign = uow.campaigns.get(campaign_id)
    if campaign is None:
        msg = "campaign not found"
        raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
    max_ord = max((r.ordinal for r in _load_runs(uow, campaign_id)), default=0)
    rec = records()
    pending = []
    for rep in range(body.repeats):
        max_ord += 1
        pending.append(
            rec.NewRun(
                campaign_id=campaign_id,
                ordinal=max_ord,
                repeat_index=rep,
                backend=campaign.backend,
                scenario_hash="manual",
                scenario_values=dict(body.values),
                x_unit=(),
                seed=0,
                phase="manual",
                tags=tuple(body.tags),
                id=new_uuid(),
            )
        )
    uow.runs.insert_batch(pending)
    uow.commit()
    return {"created": len(pending)}
