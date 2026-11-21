"""Report job routes (docs/12 §2).

Implements: T-084
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from roboprobe.api.deps import get_services
from roboprobe.api.schemas import ReportCreate, ReportJobOut
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.reporting.report_jobs import build_report_work

__all__ = ["router"]

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("", status_code=202)
def create_report(body: ReportCreate, request: Request) -> ReportJobOut:
    if body.kind not in {"campaign", "experiment"}:
        msg = "kind must be campaign or experiment"
        raise ValidationError(msg, context={"kind": body.kind})
    services = get_services(request)
    kind: Literal["campaign", "experiment"] = body.kind  # type: ignore[assignment]
    work = build_report_work(
        kind,
        body.id,
        uow_factory=services.uow_factory,
        artifact_store=services.artifact_store,
        settings=services.settings,
    )
    job = services.report_jobs.submit(kind, body.id, work)
    return ReportJobOut(
        id=job.id,
        status=job.status,
        kind=job.kind,
        target_id=job.target_id,
    )


@router.get("/{report_id}")
def report_status(report_id: UUID, request: Request) -> ReportJobOut:
    job = get_services(request).report_jobs.get(report_id)
    if job is None:
        msg = "report job not found"
        raise NotFoundError(msg, context={"report_id": str(report_id)})
    return ReportJobOut(
        id=job.id,
        status=job.status,
        kind=job.kind,
        target_id=job.target_id,
    )


@router.get("/{report_id}/content")
def report_content(report_id: UUID, request: Request) -> Response:
    job = get_services(request).report_jobs.get(report_id)
    if job is None or job.html_path is None:
        msg = "report not ready"
        raise NotFoundError(msg, context={"report_id": str(report_id)})
    if job.status != "COMPLETED":
        return JSONResponse(status_code=202, content={"status": job.status})
    return FileResponse(job.html_path, media_type="text/html")
