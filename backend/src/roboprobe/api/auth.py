"""Optional bearer-token auth and mutation content-type guard (docs/12 §1, docs/21 §1).

Implements: T-080c, NFR-SEC-001
"""

from __future__ import annotations

import hmac
from typing import Final

from fastapi import Depends, Request
from starlette.exceptions import HTTPException

from roboprobe.api.deps import get_settings
from roboprobe.core.errors import ConfigError
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.settings.api import is_loopback_host

__all__ = [
    "ALLOWED_MUTATION_TYPES",
    "SSE_EVENTS_PATH_SUFFIX",
    "assert_bind_safe",
    "require_json_mutation",
    "require_token",
]

_BEARER_PREFIX: Final = "Bearer "
SSE_EVENTS_PATH_SUFFIX: Final = "/events"
ALLOWED_MUTATION_TYPES: Final = frozenset(
    {"application/json", "application/yaml", "application/x-yaml", "text/yaml"}
)
_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def assert_bind_safe(settings: RoboProbeSettings) -> None:
    """Refuse non-loopback binds when ``api.token`` is unset (fail-fast).

    Raises:
        ConfigError: Host is not loopback and no token is configured.
    """
    if settings.api.token is not None:
        return
    if is_loopback_host(settings.api.host):
        return
    msg = f"api.token is required when api.host is not loopback (got {settings.api.host!r})"
    raise ConfigError(msg, context={"host": settings.api.host})


async def require_token(
    request: Request,
    settings: RoboProbeSettings = Depends(get_settings),
) -> None:
    """Enforce bearer auth when ``api.token`` is set.

    ``/health/live`` stays open. SSE ``GET …/events`` may pass ``?token=``.
    """
    expected = settings.api.token
    if expected is None:
        return
    if request.url.path.rstrip("/") == "/health/live":
        return
    provided = _extract_token(request)
    secret = expected.get_secret_value()
    if provided is None or not hmac.compare_digest(provided.encode(), secret.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")


async def require_json_mutation(request: Request) -> None:
    """Reject form-encoded / multipart mutations (CSRF TM-06)."""
    if request.method not in _MUTATING:
        return
    content_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if not content_type:
        return
    if content_type in ALLOWED_MUTATION_TYPES:
        return
    raise HTTPException(
        status_code=415,
        detail=f"Unsupported media type {content_type!r}; use application/json",
    )


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header is not None and header.startswith(_BEARER_PREFIX):
        return header.removeprefix(_BEARER_PREFIX).strip() or None
    if request.method == "GET" and request.url.path.rstrip("/").endswith(SSE_EVENTS_PATH_SUFFIX):
        raw = request.query_params.get("token")
        return raw if raw else None
    return None
