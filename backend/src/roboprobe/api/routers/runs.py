"""Single-run routes, replay and regression export (docs/12 §2).

Implements: T-081, T-082
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse, Response

from roboprobe.api.deps import get_services, get_uow
from roboprobe.api.downloads import artifact_path, download_response
from roboprobe.api.mapping import artifact_out, run_out
from roboprobe.api.schemas import ArtifactOut, ReplayRequest, RunOut
from roboprobe.core.clock import SystemClock
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.core.types import FailureClass, Scenario, Verdict
from roboprobe.runner.replay import ReplayRequest as ReplayBody
from roboprobe.runner.replay import enqueue_replays
from roboprobe.scenario.regression import RegressionExpect, RegressionProvenance, export_regression
from roboprobe.scenario.space import ScenarioSpace

__all__ = ["router"]

router = APIRouter(tags=["runs"])


@router.get("/runs/{run_id}")
def get_run(run_id: UUID, uow: Any = Depends(get_uow)) -> RunOut:
    run = uow.runs.get(run_id)
    if run is None:
        msg = "run not found"
        raise NotFoundError(msg, context={"run_id": str(run_id)})
    oracles = [
        {
            "oracle_id": row.oracle_id,
            "violated": row.violated,
            "robustness": row.robustness,
            "first_violation_t": row.first_violation_t,
            "details": getattr(row, "details", {}),
        }
        for row in uow.oracle_results.list_for_run(run_id)
    ]
    return run_out(run, oracles=oracles)


@router.get("/runs/{run_id}/artifacts")
def list_run_artifacts(run_id: UUID, uow: Any = Depends(get_uow)) -> list[ArtifactOut]:
    if uow.runs.get(run_id) is None:
        msg = "run not found"
        raise NotFoundError(msg, context={"run_id": str(run_id)})
    return [artifact_out(a) for a in uow.artifacts.list_for_run(run_id)]


@router.get("/artifacts/{artifact_id}/content")
def artifact_content(
    artifact_id: UUID,
    request: Request,
    uow: Any = Depends(get_uow),
) -> Response:
    art = uow.artifacts.get(artifact_id)
    if art is None:
        msg = "artifact not found"
        raise NotFoundError(msg, context={"artifact_id": str(artifact_id)})
    store = get_services(request).artifact_store
    path = artifact_path(store, art)
    run = uow.runs.get(art.run_id) if art.run_id is not None else None
    return download_response(path, art, ordinal=None if run is None else run.ordinal)


@router.post("/runs/{run_id}:replay", status_code=202)
def replay_run(
    run_id: UUID,
    body: ReplayRequest,
    request: Request,
) -> dict[str, object]:
    services = get_services(request)
    if body.repeats > services.settings.runner.max_manual_repeats:
        msg = "repeats exceeds runner.max_manual_repeats"
        raise ValidationError(msg)
    from roboprobe.runner.ports import UowFactory

    ids = enqueue_replays(
        cast(UowFactory, services.uow_factory),
        ReplayBody(run_id=run_id, repeats=body.repeats, fresh_seeds=body.fresh_seeds),
    )
    return {"run_ids": [str(rid) for rid in ids]}


@router.get("/runs/{run_id}/scenario.yaml", response_class=PlainTextResponse)
def export_scenario(
    run_id: UUID, request: Request, response: Response, uow: Any = Depends(get_uow)
) -> str:
    response.headers["Content-Disposition"] = f'attachment; filename="{run_id}-scenario.yaml"'
    response.headers["Content-Type"] = "application/yaml"
    run = uow.runs.get(run_id)
    if run is None:
        msg = "run not found"
        raise NotFoundError(msg, context={"run_id": str(run_id)})
    campaign = uow.campaigns.get(run.campaign_id)
    if campaign is None:
        msg = "campaign not found"
        raise NotFoundError(msg)
    space_def = uow.spaces.get(campaign.space_id, campaign.space_version)
    if space_def is None:
        msg = "space not found"
        raise NotFoundError(msg)
    import yaml

    space = ScenarioSpace.from_text(
        yaml.safe_dump(space_def.definition),
        source="db",
        base_dir=get_services(request).space_root,
    )
    scenario = Scenario(
        space_id=space.id,
        space_version=space.version,
        values=dict(run.scenario_values),
        scenario_hash=run.scenario_hash,
    )
    expect = None
    if run.verdict is not None:
        fc = None
        if run.primary_failure is not None:
            fc = FailureClass(str(run.primary_failure))
        expect = RegressionExpect(
            verdict=Verdict(str(getattr(run.verdict, "value", run.verdict))),
            failure_class=fc,
        )
    return export_regression(
        scenario,
        seed=run.seed,
        provenance=RegressionProvenance(source_run=run_id, exported_at=SystemClock().now()),
        expect=expect,
    )
