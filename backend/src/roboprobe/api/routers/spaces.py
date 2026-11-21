"""Scenario space routes (docs/12 §2).

Implements: T-081
"""

from __future__ import annotations

from typing import Any

import yaml
from fastapi import APIRouter, Depends, Request

from roboprobe.api._store import records
from roboprobe.api.campaign_create import parse_space_body
from roboprobe.api.deps import get_services, get_uow
from roboprobe.api.mapping import space_out
from roboprobe.api.pagination import Page, clamp_limit
from roboprobe.api.schemas import SpaceOut
from roboprobe.core.errors import NotFoundError
from roboprobe.scenario.space import ScenarioSpace

__all__ = ["router"]

router = APIRouter(prefix="/spaces", tags=["spaces"])


@router.get("")
def list_spaces(
    request: Request,
    limit: int | None = None,
    cursor: str | None = None,
    uow: Any = Depends(get_uow),
) -> Page[SpaceOut]:
    """List registered scenario spaces."""
    settings = request.app.state.settings
    page = uow.spaces.list(
        limit=clamp_limit(
            limit,
            default=settings.api.page_limit_default,
            maximum=settings.api.page_limit_max,
        ),
        cursor=cursor,
    )
    return Page(items=[space_out(item) for item in page.items], next_cursor=page.next_cursor)


@router.post("", status_code=201)
async def register_space(request: Request, uow: Any = Depends(get_uow)) -> SpaceOut:
    """Register a space from YAML or JSON body."""
    raw = await request.body()
    content_type = request.headers.get("content-type", "application/json")
    definition = parse_space_body(raw, content_type)
    services = get_services(request)
    space = ScenarioSpace.from_text(
        yaml.safe_dump(definition), source="api", base_dir=services.space_root
    )
    rec = records()
    row = rec.SpaceRecord(
        id=space.id,
        version=space.version,
        name=space.name,
        definition=definition,
        schema_version=int(str(definition.get("schema_version", 1))),
    )
    existing = uow.spaces.get(space.id, space.version)
    if existing is None:
        uow.spaces.add(row)
        uow.commit()
    return space_out(existing or row)


@router.post("/validate")
async def validate_space(request: Request) -> dict[str, str]:
    """Validate a space document without persisting."""
    raw = await request.body()
    content_type = request.headers.get("content-type", "application/json")
    parse_space_body(raw, content_type)
    return {"status": "ok"}


@router.get("/{space_id}/versions/{version}")
def get_space(space_id: str, version: str, uow: Any = Depends(get_uow)) -> dict[str, Any]:
    """Return a stored space definition."""
    row = uow.spaces.get(space_id, version)
    if row is None:
        msg = "space not found"
        raise NotFoundError(msg, context={"space_id": space_id, "version": version})
    return {
        "id": row.id,
        "version": row.version,
        "name": row.name,
        "definition": dict(row.definition),
    }
