"""Experiment routes (docs/12 §2).

Implements: T-084
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pydantic
from fastapi import APIRouter, Depends, Header, Request, Response

from roboprobe.api._store import new_uuid, records
from roboprobe.api.concurrency import assert_if_match, format_etag
from roboprobe.api.deps import get_services, get_uow
from roboprobe.api.experiment_create import plan_experiment, stage_campaigns
from roboprobe.api.mapping import experiment_out
from roboprobe.api.pagination import Page, clamp_limit
from roboprobe.api.schemas import (
    ExperimentComparisonOut,
    ExperimentCreate,
    ExperimentNotes,
    ExperimentOut,
)
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.experiments.comparison import read_campaign_runs, resolve_comparison
from roboprobe.experiments.planner import ExperimentDesign
from roboprobe.experiments.runner import _as_campaign_row

__all__ = ["router"]

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.get("")
def list_experiments(
    request: Request,
    limit: int | None = None,
    cursor: str | None = None,
    uow: Any = Depends(get_uow),
) -> Page[ExperimentOut]:
    settings = request.app.state.settings
    page = uow.experiments.list(
        limit=clamp_limit(
            limit,
            default=settings.api.page_limit_default,
            maximum=settings.api.page_limit_max,
        ),
        cursor=cursor,
    )
    return Page(items=[experiment_out(r) for r in page.items], next_cursor=page.next_cursor)


@router.post("", status_code=201)
def create_experiment(
    body: ExperimentCreate, request: Request, response: Response, uow: Any = Depends(get_uow)
) -> ExperimentOut:
    try:
        design = ExperimentDesign.model_validate(body.design)
    except pydantic.ValidationError as exc:
        raise ValidationError(str(exc)) from exc
    services = get_services(request)
    launch = (
        plan_experiment(design, body.design, uow=uow, services=services) if body.start else None
    )
    rec = records()
    eid = new_uuid()
    uow.experiments.add(
        rec.ExperimentRecord(
            id=eid,
            name=design.name or design.id,
            design=body.design,
            status="CREATED",
        )
    )
    if launch is not None:
        stage_campaigns(eid, launch[1], uow=uow, services=services)
    uow.commit()
    row = uow.experiments.get(eid)
    if row is None:
        msg = "experiment not found after create"
        raise NotFoundError(msg, context={"experiment_id": str(eid)})
    response.headers["Location"] = f"{services.settings.api.base_path}/experiments/{eid}"
    if launch is not None:
        result = _experiment_detail(row, uow)
        services.experiment_jobs.submit(eid, design, launch[0])
        return result
    return experiment_out(row)


@router.get("/{experiment_id}")
def get_experiment(
    experiment_id: UUID, response: Response, uow: Any = Depends(get_uow)
) -> ExperimentOut:
    row = uow.experiments.get(experiment_id)
    if row is None:
        msg = "experiment not found"
        raise NotFoundError(msg, context={"experiment_id": str(experiment_id)})
    response.headers["ETag"] = format_etag(getattr(row, "etag_version", 1))
    return _experiment_detail(row, uow)


def _experiment_detail(row: Any, uow: Any) -> ExperimentOut:
    payload = experiment_out(row)
    campaigns = uow.campaigns.list_for_experiment(row.id)
    payload.cells = [
        {
            "campaign_id": str(c.id),
            "strategy_id": c.strategy_id,
            "seed": c.seed,
            "budget": c.budget,
            "status": getattr(c.status, "value", c.status),
            "rep": c.experiment_rep,
        }
        for c in campaigns
    ]
    payload.progress = {
        "completed": sum(c.status == "COMPLETED" for c in campaigns),
        "total": len(campaigns),
    }
    return payload


@router.patch("/{experiment_id}")
def patch_experiment_notes(
    experiment_id: UUID,
    body: ExperimentNotes,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    uow: Any = Depends(get_uow),
) -> ExperimentOut:
    """Save threats notes with optimistic concurrency."""
    row = uow.experiments.get(experiment_id)
    if row is None:
        msg = "experiment not found"
        raise NotFoundError(msg)
    etag = getattr(row, "etag_version", 1)
    assert_if_match(if_match, etag)
    uow.experiments.patch_notes(experiment_id, body.notes, etag)
    uow.commit()
    response.headers["ETag"] = format_etag(etag + 1)
    return experiment_out(uow.experiments.get(experiment_id))


@router.get("/{experiment_id}/comparison")
def experiment_comparison(
    experiment_id: UUID,
    request: Request,
    uow: Any = Depends(get_uow),
) -> ExperimentComparisonOut:
    row = uow.experiments.get(experiment_id)
    if row is None:
        msg = "experiment not found"
        raise NotFoundError(msg, context={"experiment_id": str(experiment_id)})
    campaigns = (
        []
        if row.results
        else [_as_campaign_row(c) for c in uow.campaigns.list_for_experiment(experiment_id)]
    )
    runs_by = {campaign.id: read_campaign_runs(uow.runs, campaign.id) for campaign in campaigns}
    payload = resolve_comparison(
        experiment_id, row, campaigns, runs_by, get_services(request).settings.experiments
    )
    return ExperimentComparisonOut.model_validate(payload)
