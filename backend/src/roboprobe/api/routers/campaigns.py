"""Campaign CRUD and lifecycle (docs/12 §2, §5).

Implements: T-081
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

import yaml
from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import JSONResponse

from roboprobe.analysis.base import AnalysisKind
from roboprobe.api.campaign_create import create_campaign
from roboprobe.api.campaign_idempotency import cached_campaign, remember_campaign
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
    RunOut,
)
from roboprobe.core.clock import SystemClock
from roboprobe.core.errors import ConflictError, ErrorCode, NotFoundError, ValidationError
from roboprobe.core.seeding import RUN, derive_seed
from roboprobe.core.types import CampaignStatus, FailureClass, RunStatus, Verdict
from roboprobe.scenario.space import ScenarioSpace

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
def list_campaigns(  # noqa: PLR0913, PLR0917 - public campaign filters
    request: Request,
    limit: int | None = None,
    cursor: str | None = None,
    status: CampaignStatus | None = None,
    strategy: str | None = None,
    backend: str | None = None,
    uow: Any = Depends(get_uow),
) -> Page[CampaignOut]:
    settings = request.app.state.settings
    size = clamp_limit(
        limit, default=settings.api.page_limit_default, maximum=settings.api.page_limit_max
    )
    query = getattr(uow.campaigns, "query", None)
    if callable(query):
        page = query(
            limit=size,
            cursor=cursor,
            status=None if status is None else status.value,
            strategy=strategy,
            backend=backend,
        )
    else:
        page = uow.campaigns.list(limit=size, cursor=cursor)
    base = _base_path(request)
    run_counter = getattr(uow.runs, "counts_for_campaigns", None)
    mode_counter = getattr(uow.modes, "counts_for_campaigns", None)
    ids = [row.id for row in page.items]
    run_counts = run_counter(ids) if callable(run_counter) else None
    mode_counts = mode_counter(ids) if callable(mode_counter) else None
    items = []
    for row in page.items:
        if run_counts is None:
            counts = campaign_counts(_load_runs(uow, row.id), budget=row.budget)
        else:
            counts = {**campaign_counts([], budget=row.budget), **run_counts.get(row.id, {})}
        counts["modes_found"] = (
            len(uow.modes.list_for_campaign(row.id))
            if mode_counts is None
            else mode_counts.get(row.id, 0)
        )
        items.append(campaign_out(row, base_path=base, counts=counts))
    return Page(items=items, next_cursor=page.next_cursor)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CampaignOut)
async def create_campaign_route(
    body: CampaignCreate,
    request: Request,
    response: Response,
    uow: Any = Depends(get_uow),
) -> CampaignOut | JSONResponse:
    raw = await request.body()
    cached = cached_campaign(request, raw, uow)
    if cached is not None:
        return cached
    services = get_services(request)
    cid = create_campaign(
        body,
        uow=uow,
        settings=services.settings,
        campaigns=services.campaigns,
        space_root=services.space_root,
    )
    row = uow.campaigns.get(cid)
    if row is None:
        msg = "campaign not found after create"
        raise NotFoundError(msg, context={"campaign_id": str(cid)})
    response.headers["Location"] = f"{_base_path(request)}/campaigns/{cid}"
    payload = campaign_out(row, base_path=_base_path(request))
    remember_campaign(request, raw, payload.model_dump(mode="json"), uow)
    uow.commit()
    return payload


@router.get("/{campaign_id}", response_model=CampaignOut)
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


@router.patch("/{campaign_id}", response_model=CampaignOut)
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
    result = campaign_out(row, base_path=_base_path(request))
    if cmd == "start":
        now = SystemClock().now()
        online = getattr(uow.workers, "online", None)
        workers = online(row.backend) if callable(online) else uow.workers.list().items
        active = any(
            worker.last_heartbeat is not None
            and (now - worker.last_heartbeat).total_seconds()
            <= services.settings.runner.heartbeat_timeout_s
            for worker in workers
        )
        if not active:
            result.warnings.append(
                {"code": "NO_WORKERS", "message": "No online worker supports this backend."}
            )
    return result


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
    ordinals = {run.id: run.ordinal for run in runs}
    modes = uow.modes.list_for_campaign(campaign_id)
    first_seen = sorted(
        ordinals[mode.first_seen_run]
        for mode in modes
        if getattr(mode, "first_seen_run", None) in ordinals
    )
    for unique_modes, ordinal in enumerate(first_seen, start=1):
        curve.append({"run_ordinal": ordinal, "unique_modes": unique_modes})
    counts["modes_found"] = len(modes)
    return CampaignProgress(campaign_id=campaign_id, counts=counts, discovery_curve=curve)


@router.get("/{campaign_id}/runs", response_model=Page[RunOut])
def list_runs(  # noqa: PLR0913, PLR0917 - documented run filters
    campaign_id: UUID,
    request: Request,
    limit: int | None = None,
    cursor: str | None = None,
    status: RunStatus | None = None,
    verdict: Verdict | None = None,
    phase: str | None = None,
    failure_class: FailureClass | None = None,
    tag: Annotated[list[str] | None, Query()] = None,
    sort: Literal[
        "ordinal", "-ordinal", "finished_at", "-finished_at", "robustness", "-robustness"
    ] = "ordinal",
    uow: Any = Depends(get_uow),
) -> Page[dict[str, object]]:
    from roboprobe.api.mapping import run_out

    if uow.campaigns.get(campaign_id) is None:
        msg = "campaign not found"
        raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
    settings = request.app.state.settings
    size = clamp_limit(
        limit, default=settings.api.page_limit_default, maximum=settings.api.page_limit_max
    )
    query = getattr(uow.runs, "query_for_campaign", None)
    if callable(query):
        page = query(
            campaign_id,
            limit=size,
            cursor=cursor,
            sort=sort,
            status=None if status is None else status.value,
            verdict=None if verdict is None else verdict.value,
            phase=phase,
            failure_class=None if failure_class is None else failure_class.value,
            tags=tuple(tag or ()),
        )
    else:
        page = uow.runs.list_for_campaign(campaign_id, limit=size, cursor=cursor)
    items = [run_out(r).model_dump(mode="json") for r in page.items]
    return Page(items=items, next_cursor=page.next_cursor)


@router.post("/{campaign_id}/runs", status_code=status.HTTP_201_CREATED, response_model=None)
async def add_manual_runs(
    campaign_id: UUID,
    body: ManualRunCreate,
    request: Request,
    uow: Any = Depends(get_uow),
) -> dict[str, object] | JSONResponse:
    from roboprobe.api._store import new_uuid, records

    raw = await request.body()
    cached = cached_campaign(request, raw, uow)
    if cached is not None:
        return cached

    campaign = uow.campaigns.get(campaign_id)
    if campaign is None:
        msg = "campaign not found"
        raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
    settings = get_services(request).settings
    if body.repeats <= 0:
        msg = "repeats must be positive"
        raise ValidationError(msg)
    if body.repeats > settings.runner.max_manual_repeats:
        msg = "repeats exceeds runner.max_manual_repeats"
        raise ValidationError(msg)
    stored = uow.spaces.get(campaign.space_id, campaign.space_version)
    if stored is None:
        msg = "registered campaign space not found"
        raise NotFoundError(msg)
    space = ScenarioSpace.from_text(
        yaml.safe_dump(stored.definition),
        source="registered campaign space",
        base_dir=get_services(request).space_root,
    ).with_pins(campaign.pins)
    scenario = space.make_scenario(body.values)
    lock = f"manual:{campaign_id}"
    if not uow.try_advisory_lock(lock):
        msg = "another manual request is being enqueued; retry"
        raise ConflictError(msg)
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
                scenario_hash=scenario.scenario_hash,
                scenario_values=dict(scenario.values),
                x_unit=tuple(float(v) for v in space.to_unit(scenario.values)),
                seed=derive_seed(campaign.seed, RUN, max_ord),
                phase="manual",
                tags=tuple(body.tags),
                id=new_uuid(),
                priority=settings.runner.manual_priority,
            )
        )
    ids = uow.runs.insert_batch(pending)
    payload = {"created": len(ids), "run_ids": [str(rid) for rid in ids]}
    remember_campaign(request, raw, payload, uow)
    uow.commit()
    return payload
