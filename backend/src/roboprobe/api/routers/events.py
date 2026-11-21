"""``GET /events`` server-sent stream (docs/12 §4).

Layer: Interface (L4).

Implements: T-083b, FR-API-002
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sse_starlette import EventSourceResponse, ServerSentEvent

from roboprobe.api.sse import EventHub, OutboxEvent

__all__ = ["router"]

router = APIRouter(tags=["events"])


def _ping() -> ServerSentEvent:
    """Comment frame ``: ping`` (docs/12 §4)."""
    return ServerSentEvent(comment="ping")


def _frame(event: OutboxEvent) -> dict[str, str]:
    return {
        "id": str(event.id),
        "event": event.type,
        "data": json.dumps(event.payload, separators=(",", ":"), sort_keys=True),
    }


def _resume_cursor(request: Request, query_cursor: int | None) -> int | None:
    """``Last-Event-ID`` wins over the ``last_event_id`` query parameter."""
    header = request.headers.get("last-event-id")
    if header is None:
        return query_cursor
    if not header.strip().isdigit():
        raise HTTPException(status_code=400, detail="Last-Event-ID must be a non-negative integer")
    return int(header.strip())


@router.get("/events")
async def stream_events(
    request: Request,
    campaign_id: UUID | None = None,
    last_event_id: int | None = None,
) -> EventSourceResponse:
    """Stream outbox events. ``Last-Event-ID`` resumes after that id."""
    cursor = _resume_cursor(request, last_event_id)
    hub: EventHub = request.app.state.event_hub
    subscription = hub.subscribe(campaign_id, cursor)
    ping = request.app.state.settings.api.sse.ping_interval_s

    async def frames() -> AsyncIterator[dict[str, str]]:
        try:
            async for event in subscription:
                if await request.is_disconnected():
                    break
                yield _frame(event)
        finally:
            await subscription.aclose()

    return EventSourceResponse(frames(), ping=ping, ping_message_factory=_ping)
