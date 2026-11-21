"""Experiment routes (docs/12 §2).

Implements: T-084
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import numpy as np
import pydantic
from fastapi import APIRouter, Depends, Header, Request, Response

from roboprobe.api._store import new_uuid, records
from roboprobe.api.concurrency import assert_if_match, format_etag
from roboprobe.api.deps import get_services, get_uow
from roboprobe.api.mapping import experiment_out
from roboprobe.api.pagination import Page, clamp_limit
from roboprobe.api.schemas import (
    ExperimentComparisonOut,
    ExperimentCreate,
    ExperimentNotes,
    ExperimentOut,
)
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.experiments.planner import ExperimentDesign
from roboprobe.experiments.runner import _as_campaign_row, build_comparison
from roboprobe.metrics.campaign_metrics import CampaignRun, comparison_runs

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
def create_experiment(body: ExperimentCreate, uow: Any = Depends(get_uow)) -> ExperimentOut:
    try:
        design = ExperimentDesign.model_validate(body.design)
    except pydantic.ValidationError as exc:
        raise ValidationError(str(exc)) from exc
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
    uow.commit()
    row = uow.experiments.get(eid)
    if row is None:
        msg = "experiment not found after create"
        raise NotFoundError(msg, context={"experiment_id": str(eid)})
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
    payload = experiment_out(row)
    payload.cells = [
        {
            "campaign_id": str(c.id),
            "strategy_id": c.strategy_id,
            "seed": c.seed,
            "budget": c.budget,
            "status": getattr(c.status, "value", c.status),
            "rep": c.experiment_rep,
        }
        for c in uow.campaigns.list_for_experiment(experiment_id)
    ]
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
    campaigns = uow.campaigns.list_for_experiment(experiment_id)
    runs_by: dict[UUID, list[CampaignRun]] = {}
    for camp in campaigns:
        runs: list[CampaignRun] = []
        cursor: str | None = None
        while True:
            page = uow.runs.list_for_campaign(camp.id, limit=None, cursor=cursor)
            for r in page.items:
                if r.verdict is None:
                    continue
                runs.append(
                    CampaignRun(
                        verdict=r.verdict,
                        wall_time_s=float((r.metrics or {}).get("duration_s", 0.0)),
                        x_unit=tuple(float(x) for x in r.x_unit),
                        phase=str(r.phase or ""),
                        tags=tuple(str(t) for t in r.tags),
                    )
                )
            cursor = page.next_cursor
            if cursor is None:
                break
        runs_by[camp.id] = list(comparison_runs(tuple(runs)))
    if not campaigns:
        return ExperimentComparisonOut(experiment_id=experiment_id)
    services = get_services(request)
    design = ExperimentDesign.model_validate(row.design)
    metrics = tuple(design.metrics) if design.metrics else ("MET-01", "MET-03")
    payload = build_comparison(
        experiment_id,
        [_as_campaign_row(c) for c in campaigns],
        runs_by,
        metrics=metrics,
        settings=services.settings.experiments,
        rng=np.random.default_rng(services.settings.experiments.reference_set.seed),
    )
    return ExperimentComparisonOut(
        experiment_id=experiment_id,
        metrics=[str(m) for m in cast(list[object], payload.get("metrics", []))],
        strategies=cast(dict[str, dict[str, object]], payload.get("strategies", {})),
        tests=cast(list[dict[str, object]], payload.get("tests", [])),
    )
