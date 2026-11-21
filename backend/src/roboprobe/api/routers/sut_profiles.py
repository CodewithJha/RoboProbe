"""SUT profile routes (docs/12 §2).

Implements: T-081
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from roboprobe.api._store import records
from roboprobe.api.deps import get_uow
from roboprobe.api.mapping import sut_out
from roboprobe.api.pagination import Page, clamp_limit
from roboprobe.api.schemas import SutProfileCreate, SutProfileOut

__all__ = ["router"]

router = APIRouter(prefix="/sut-profiles", tags=["sut-profiles"])


@router.get("")
def list_profiles(
    request: Request,
    limit: int | None = None,
    cursor: str | None = None,
    uow: Any = Depends(get_uow),
) -> Page[SutProfileOut]:
    settings = request.app.state.settings
    page = uow.sut_profiles.list(
        limit=clamp_limit(
            limit,
            default=settings.api.page_limit_default,
            maximum=settings.api.page_limit_max,
        ),
        cursor=cursor,
    )
    return Page(items=[sut_out(item) for item in page.items], next_cursor=page.next_cursor)


@router.post("", status_code=201)
def create_profile(body: SutProfileCreate, uow: Any = Depends(get_uow)) -> SutProfileOut:
    import hashlib
    import json

    digest = hashlib.sha256(
        json.dumps(body.config, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    rec = records()
    row = rec.SutProfileRecord(
        id=body.id,
        backend=body.backend,
        config=dict(body.config),
        config_hash=digest,
    )
    if uow.sut_profiles.get(body.id) is None:
        uow.sut_profiles.add(row)
        uow.commit()
        return sut_out(row)
    return sut_out(uow.sut_profiles.get(body.id))
