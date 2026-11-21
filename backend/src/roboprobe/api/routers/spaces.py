"""Scenario-space endpoints (``GET/POST /spaces``, docs/12 §2).

Thin HTTP adapter over :class:`roboprobe.runner.catalog.SpaceService`; the CLI ``space`` commands
use the same service (T-045a).

Layer: Interface (L4).

Implements: T-081a, FR-API-001, FR-SCN-001, UC-01
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, Request, Response

from roboprobe.api.body import max_upload_bytes, read_upload
from roboprobe.api.catalog_schemas import (
    SpaceSummary,
    SpaceValidationResult,
    SpaceVersion,
    space_summary,
    space_validation,
    space_version,
)
from roboprobe.api.deps import ServicesProto, get_services, get_settings
from roboprobe.api.pagination import Page, clamp_limit
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.runner.catalog import SpaceService
from roboprobe.runner.ports import UowFactory

__all__ = ["router"]

router = APIRouter(tags=["spaces"])

Services = Annotated[ServicesProto, Depends(get_services)]
Settings = Annotated[RoboProbeSettings, Depends(get_settings)]

_SPACE_BODY: dict[str, Any] = {
    "requestBody": {
        "required": False,
        "description": "Scenario-space document (YAML or JSON; JSON is valid YAML).",
        "content": {
            "application/yaml": {"schema": {"type": "object"}},
            "application/json": {"schema": {"type": "object"}},
        },
    }
}


def _service(services: ServicesProto, *, max_bytes: int | None = None) -> SpaceService:
    return SpaceService(
        cast("UowFactory", services.uow_factory),
        base_dir=services.space_root,
        max_bytes=max_bytes,
    )


@router.get(
    "/spaces",
    response_model=Page[SpaceSummary],
    summary="List registered scenario spaces",
)
def list_spaces(
    services: Services,
    settings: Settings,
    limit: Annotated[int | None, Query(ge=1)] = None,
    cursor: str | None = None,
) -> Page[SpaceSummary]:
    """Return one keyset page of spaces, ordered by ``id`` then ``version``."""
    page = _service(services).list(
        limit=clamp_limit(
            limit, default=settings.api.page_limit_default, maximum=settings.api.page_limit_max
        ),
        cursor=cursor,
    )
    return Page(
        items=[space_summary(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.post(
    "/spaces",
    response_model=SpaceVersion,
    status_code=201,
    openapi_extra=_SPACE_BODY,
    summary="Validate and register a scenario space",
)
async def register_space(
    request: Request,
    response: Response,
    services: Services,
    settings: Settings,
) -> SpaceVersion:
    """Register a YAML/JSON space; identical content is idempotent (200, same version)."""
    raw = await read_upload(request, max_bytes=max_upload_bytes(settings))
    result = _service(services, max_bytes=max_upload_bytes(settings)).register_bytes(raw)
    response.status_code = 201 if result.created else 200
    return space_version(result.item)


@router.post(
    "/spaces/validate",
    response_model=SpaceValidationResult,
    openapi_extra=_SPACE_BODY,
    summary="Validate a scenario space without storing it",
)
async def validate_space(
    request: Request,
    services: Services,
    settings: Settings,
) -> SpaceValidationResult:
    """Validate a YAML/JSON space; invalid input still returns 200 with ``valid: false``."""
    raw = await read_upload(request, max_bytes=max_upload_bytes(settings))
    result = _service(services, max_bytes=max_upload_bytes(settings)).validate_bytes(raw)
    return space_validation(result)


@router.get(
    "/spaces/{space_id}/versions/{version}",
    response_model=SpaceVersion,
    summary="Get one stored space version",
)
def get_space_version(space_id: str, version: str, services: Services) -> SpaceVersion:
    """Return the stored definition of ``(space_id, version)``."""
    return space_version(_service(services).get(space_id, version))
