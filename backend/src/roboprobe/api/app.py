"""FastAPI application factory (docs/05 §10, docs/12 §1).

Implements: T-080a, T-080b, T-080c, FR-API-001, NFR-OBS-001, NFR-SEC-001
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from roboprobe.api.auth import assert_bind_safe, require_json_mutation, require_token
from roboprobe.api.errors import install_error_handlers
from roboprobe.api.routers import ROUTERS
from roboprobe.api.routers import health as health_router
from roboprobe.api.routers import meta as meta_router
from roboprobe.core.logging import bind_context
from roboprobe.core.metrics_registry import Metrics, create_metrics
from roboprobe.core.settings import RoboProbeSettings, load_settings
from roboprobe.observability.tracing import (
    configure_tracing,
    current_trace_id,
    instrument_fastapi,
)

__all__ = ["GZIP_MINIMUM_SIZE", "create_app"]

GZIP_MINIMUM_SIZE = 1024
"""Compress responses at or above this size [bytes] (docs/12 §7)."""

_CORS_HEADERS = ["Authorization", "Content-Type", "If-Match", "Idempotency-Key", "Last-Event-ID"]


def create_app(settings: RoboProbeSettings | None = None) -> FastAPI:
    """Build the HTTP API. Import-safe: no I/O until lifespan / first request.

    Args:
        settings: Resolved settings; ``load_settings()`` when ``None``.
    """
    resolved = settings if settings is not None else load_settings()
    assert_bind_safe(resolved)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            services = getattr(app.state, "services", None)
            close = getattr(services, "close", None)
            if callable(close):
                close()

    app = FastAPI(
        title="RoboProbe API",
        version="v1",
        lifespan=lifespan,
        docs_url=f"{resolved.api.base_path}/docs",
        openapi_url=f"{resolved.api.base_path}/openapi.json",
    )
    app.state.settings = resolved
    if not hasattr(app.state, "services"):
        app.state.services = _LazyServices(resolved)

    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.api.cors_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=_CORS_HEADERS,
        expose_headers=["ETag"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=GZIP_MINIMUM_SIZE)
    app.add_middleware(_AccessLogMiddleware)
    app.add_middleware(_TraceIdMiddleware)

    deps = [Depends(require_token), Depends(require_json_mutation)]
    app.include_router(health_router.router, dependencies=deps)
    app.include_router(meta_router.router, prefix=resolved.api.base_path, dependencies=deps)
    for router in ROUTERS:
        if router is health_router.router or router is meta_router.router:
            continue
        app.include_router(router, prefix=resolved.api.base_path, dependencies=deps)

    metrics: Metrics = create_metrics(enabled=resolved.observability.metrics_enabled)
    app.state.metrics = metrics
    if resolved.observability.metrics_enabled and metrics.registry is not None:
        from prometheus_client import make_asgi_app

        app.mount("/metrics", make_asgi_app(registry=metrics.registry))

    configure_tracing(
        resolved.observability, resolved.observability.service_name or "roboprobe-api"
    )
    instrument_fastapi(app)
    return app


class _LazyServices:
    """Defer ``build_api`` until first attribute access (keeps import side-effect free)."""

    def __init__(self, settings: RoboProbeSettings) -> None:
        self._settings = settings
        self._inner: Any | None = None

    def _ensure(self) -> Any:
        if self._inner is None:
            from roboprobe.bootstrap.api import build_api

            self._inner = build_api(self._settings)
        return self._inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ensure(), name)

    def close(self) -> None:
        if self._inner is not None:
            self._inner.close()


class _TraceIdMiddleware:
    """Pure ASGI middleware (avoids BaseHTTPMiddleware body-consumption bugs)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        trace_id = headers.get("x-trace-id") or current_trace_id() or str(uuid.uuid4())
        scope.setdefault("state", {})
        # Starlette request.state is populated from scope["state"] when present.
        state = scope.get("state")
        if isinstance(state, dict):
            state["trace_id"] = trace_id
        else:
            scope["state"] = {"trace_id": trace_id}

        async def send_with_trace(message: Message) -> None:
            if message["type"] == "http.response.start":
                raw_headers = list(message.get("headers", []))
                raw_headers.append((b"x-trace-id", trace_id.encode()))
                message = {**message, "headers": raw_headers}
            await send(message)

        with bind_context(trace_id=trace_id):
            await self.app(scope, receive, send_with_trace)


class _AccessLogMiddleware:
    """Log ``api.request`` with route template and observe latency histogram."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        await self.app(scope, receive, send_wrapper)
        duration_ms = (time.perf_counter() - started) * 1000.0
        route = scope.get("route")
        path = scope.get("path", "")
        template = getattr(route, "path", path)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        query = scope.get("query_string", b"").decode()
        token = ""
        for part in query.split("&"):
            if part.startswith("token="):
                token = part.removeprefix("token=")
        structlog.get_logger("api").info(
            "api.request",
            method=scope.get("method"),
            route=template,
            status=status_code,
            duration_ms=round(duration_ms, 3),
            authorization=headers.get("authorization"),
            token=token or None,
        )
        app_obj = scope.get("app")
        metrics = getattr(getattr(app_obj, "state", None), "metrics", None)
        if metrics is not None:
            metrics.api_request_duration_seconds.labels(
                route=template,
                method=str(scope.get("method")),
                status=str(status_code),
            ).observe(duration_ms / 1000.0)
