"""Persistent campaign response replay (T-081b, FR-API-001)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

from fastapi import Request
from fastapi.responses import JSONResponse

from roboprobe.api.idempotency import IdempotencyStore, remember, replay_or_begin
from roboprobe.core.clock import SystemClock
from roboprobe.core.errors import ConflictError, ValidationError

__all__ = ["cached_campaign", "remember_campaign"]


def cached_campaign(request: Request, body: bytes, uow: Any) -> JSONResponse | None:
    """Replay a successfully committed create response when the key matches."""
    key = request.headers.get("idempotency-key")
    if key is None:
        return None
    store = _store(request, uow)
    lock = getattr(store, "try_lock", None)
    if not callable(lock) or not lock(key):
        msg = "this idempotent request is in progress; retry"
        raise ConflictError(msg)
    store.delete_older_than(
        SystemClock().now() - timedelta(seconds=request.app.state.settings.api.idempotency_ttl_s)
    )
    cached = replay_or_begin(
        store, key=key, method=request.method, path=request.url.path, body=body
    )
    if cached is None:
        return None
    headers = {}
    if isinstance(cached.response_json, dict) and "id" in cached.response_json:
        headers["Location"] = f"{request.url.path}/{cached.response_json['id']}"
    return JSONResponse(cached.response_json, status_code=cached.status, headers=headers)


def remember_campaign(request: Request, body: bytes, response: dict[str, Any], uow: Any) -> None:
    """Persist successful responses; failed validation never reserves a key."""
    key = request.headers.get("idempotency-key")
    if key is not None:
        remember(
            _store(request, uow),
            key=key,
            method=request.method,
            path=request.url.path,
            body=body,
            status=201,
            response_json=response,
            created_at=SystemClock().now(),
        )


def _store(request: Request, uow: Any) -> IdempotencyStore:
    store = getattr(uow, "idempotency", None)
    if store is None:
        msg = "Idempotency store is not configured"
        raise ValidationError(msg)
    return cast("IdempotencyStore", store)
