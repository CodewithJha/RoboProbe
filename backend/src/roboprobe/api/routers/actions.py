"""Asynchronous campaign bundle exports (T-082c, FR-STO-003)."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from roboprobe.api.deps import get_services, get_uow
from roboprobe.api.schemas import ReportJobOut
from roboprobe.bootstrap.exports import bundle_work
from roboprobe.core.errors import NotFoundError

__all__ = ["router"]
router = APIRouter(tags=["actions"])


@router.post("/campaigns/{campaign_id}:export", status_code=202)
def export_campaign(
    campaign_id: UUID, request: Request, uow: Any = Depends(get_uow)
) -> ReportJobOut:
    """Export via the shared job status/content endpoints without blocking HTTP."""
    if uow.campaigns.get(campaign_id) is None:
        msg = "campaign not found"
        raise NotFoundError(msg)
    services = get_services(request)
    work = bundle_work(
        campaign_id,
        uow_factory=services.uow_factory,
        artifact_store=services.artifact_store,
        settings=services.settings,
    )
    job = services.report_jobs.submit("bundle", campaign_id, work)
    return ReportJobOut(
        id=job.id,
        report_id=job.id,
        status=job.status,
        kind=job.kind,
        target_id=job.target_id,
        status_url=f"{services.settings.api.base_path}/reports/{job.id}",
    )
