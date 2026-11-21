"""Worker health routes (docs/12 §2).

Implements: T-081
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from roboprobe.api.deps import get_uow
from roboprobe.api.mapping import worker_out
from roboprobe.api.pagination import Page, clamp_limit
from roboprobe.api.schemas import WorkerOut

__all__ = ["router"]

router = APIRouter(prefix="/workers", tags=["workers"])


@router.get("")
def list_workers(
    request: Request,
    limit: int | None = None,
    cursor: str | None = None,
    uow: Any = Depends(get_uow),
) -> Page[WorkerOut]:
    settings = request.app.state.settings
    page = uow.workers.list(
        limit=clamp_limit(
            limit,
            default=settings.api.page_limit_default,
            maximum=settings.api.page_limit_max,
        ),
        cursor=cursor,
    )
    return Page(items=[worker_out(w) for w in page.items], next_cursor=page.next_cursor)
