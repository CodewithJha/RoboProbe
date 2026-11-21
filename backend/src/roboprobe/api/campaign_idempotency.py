"""Persistent campaign response replay (T-081b, FR-API-001)."""

from __future__ import annotations

from typing import Any, cast

from fastapi import Request
from fastapi.responses import JSONResponse

from roboprobe.api.idempotency import IdempotencyStore, remember, replay_or_begin
from roboprobe.core.clock import SystemClock
from roboprobe.core.errors import ValidationError

__all__ = ["cached_campaign", "remember_campaign"]


def cached_campaign(request: Request, body: bytes) -> JSONResponse | None:
    """Replay a successfully committed create response when the key matches."""
    key = request.headers.get("idempotency-key")
    if key is None:
        return None
    store = _store(request)
    cached = replay_or_begin(
        store, key=key, method=request.method, path=request.url.path, body=body
    )
    if cached is None:
        return None
    return JSONResponse(cached.response_json, status_code=cached.status)


def remember_campaign(request: Request, body: bytes, response: dict[str, Any]) -> None:
    """Persist successful responses; failed validation never reserves a key."""
    key = request.headers.get("idempotency-key")
    if key is not None:
        remember(
            _store(request),
            key=key,
            method=request.method,
            path=request.url.path,
            body=body,
            status=201,
            response_json=response,
            created_at=SystemClock().now(),
        )


def _store(request: Request) -> IdempotencyStore:
    store = getattr(request.app.state.services, "idempotency", None)
    if store is None:
        msg = "Idempotency store is not configured"
        raise ValidationError(msg)
    return cast("IdempotencyStore", store)
