"""SUT-profile endpoints (``GET/POST /sut-profiles``, docs/12 §2).

Thin HTTP adapter over :class:`roboprobe.runner.catalog.SutProfileService`.

Layer: Interface (L4).

Implements: T-081a, FR-API-001, UC-10
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, Request, Response

from roboprobe.api.body import max_upload_bytes, read_upload
from roboprobe.api.catalog_schemas import SutProfileDTO, sut_profile_dto
from roboprobe.api.deps import ServicesProto, get_services, get_settings
from roboprobe.api.pagination import Page, clamp_limit
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.runner.catalog import SutProfileService
from roboprobe.runner.ports import UowFactory

__all__ = ["router"]

router = APIRouter(tags=["sut-profiles"])

Services = Annotated[ServicesProto, Depends(get_services)]
Settings = Annotated[RoboProbeSettings, Depends(get_settings)]

_PROFILE_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "description": "SUT profile document (YAML or JSON; JSON is valid YAML).",
        "content": {
            "application/yaml": {"schema": {"type": "object"}},
            "application/json": {"schema": {"type": "object"}},
        },
    }
}


def _service(services: ServicesProto, *, max_bytes: int | None = None) -> SutProfileService:
    return SutProfileService(
        cast("UowFactory", services.uow_factory),
        max_bytes=max_bytes,
    )


@router.get(
    "/sut-profiles",
    response_model=Page[SutProfileDTO],
    summary="List registered SUT profiles",
)
def list_sut_profiles(
    services: Services,
    settings: Settings,
    limit: Annotated[int | None, Query(ge=1)] = None,
    cursor: str | None = None,
) -> Page[SutProfileDTO]:
    """Return one keyset page of robot-stack profiles, ordered by ``id``."""
    page = _service(services).list(
        limit=clamp_limit(
            limit, default=settings.api.page_limit_default, maximum=settings.api.page_limit_max
        ),
        cursor=cursor,
    )
    return Page(
        items=[sut_profile_dto(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.post(
    "/sut-profiles",
    response_model=SutProfileDTO,
    status_code=201,
    openapi_extra=_PROFILE_BODY,
    summary="Validate and register a SUT profile",
)
async def create_sut_profile(
    request: Request,
    response: Response,
    services: Services,
    settings: Settings,
) -> SutProfileDTO:
    """Register a YAML/JSON profile; identical content is idempotent (200, same hash)."""
    raw = await read_upload(request, max_bytes=max_upload_bytes(settings))
    result = _service(services, max_bytes=max_upload_bytes(settings)).create_bytes(raw)
    response.status_code = 201 if result.created else 200
    return sut_profile_dto(result.item)
