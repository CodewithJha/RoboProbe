"""HTTP API settings (docs/27 §4.3).

Layer: Kernel (L1).
"""

from __future__ import annotations

import ipaddress
from typing import Self

from pydantic import Field, SecretStr, model_validator

from roboprobe.core.settings._base import PORT_MAX, SettingsSection

__all__ = ["ApiSettings", "SseSettings", "is_loopback_host"]

_LOOPBACK_NAMES = frozenset({"localhost"})
_DEFAULT_ERROR_TYPE_BASE = "https://github.com/CodewithJha/RoboProbe/blob/main/docs/errors.md"
# Dev-only default; set ``api.cursor_secret`` for stable cursors across restarts (T-080d).
_DEFAULT_CURSOR_SECRET = "roboprobe-dev-cursor-secret"  # noqa: S105 - HMAC key, not a password


class SseSettings(SettingsSection):
    """Server-sent events stream settings."""

    ping_interval_s: float = Field(
        default=15.0, gt=0, description="Keep-alive ping interval on SSE streams [s]."
    )
    poll_interval_s: float = Field(
        default=2.0,
        gt=0,
        description="How often the outbox listener re-reads events.id when NOTIFY is missed [s].",
    )
    queue_size: int = Field(
        default=256,
        gt=0,
        description=(
            "Per-subscriber SSE queue depth; overflow drops the oldest event and sends resync."
        ),
    )
    batch_size: int = Field(
        default=200,
        gt=0,
        description="Maximum events read from the outbox per poll [rows].",
    )
    reconnect_initial_s: float = Field(
        default=0.5,
        gt=0,
        description="Initial delay before reopening a dropped LISTEN connection [s].",
    )
    reconnect_max_s: float = Field(
        default=30.0,
        gt=0,
        description="Cap on LISTEN reconnect backoff [s].",
    )
    connect_timeout_s: float = Field(
        default=5.0,
        gt=0,
        description="TCP timeout for the dedicated LISTEN and poll connections [s].",
    )

    @model_validator(mode="after")
    def _check_backoff(self) -> Self:
        if self.reconnect_initial_s > self.reconnect_max_s:
            msg = "api.sse.reconnect_initial_s must not exceed api.sse.reconnect_max_s"
            raise ValueError(msg)
        return self


class ApiSettings(SettingsSection):
    """FastAPI server settings. A non-loopback ``host`` requires ``token``."""

    host: str = Field(
        default="127.0.0.1",
        min_length=1,
        description="Bind address; any non-loopback address requires `api.token`.",
    )
    port: int = Field(default=8000, ge=1, le=PORT_MAX, description="Listen port.")
    base_path: str = Field(
        default="/api/v1",
        pattern=r"^/[^\s]*[^/\s]$",
        description="URL prefix of the versioned API.",
    )
    token: SecretStr | None = Field(
        default=None,
        description="Bearer token required on every request (and for any non-loopback `host`).",
    )
    cors_origins: tuple[str, ...] = Field(
        default=("http://localhost:5173", "http://localhost:8080"),
        description="Origins allowed by CORS (dev server and dashboard).",
    )
    trace_default_hz: float = Field(
        default=10.0,
        gt=0,
        allow_inf_nan=False,
        description="Default JSON trace sampling target [Hz].",
    )
    trace_max_hz: float = Field(
        default=50.0,
        gt=0,
        allow_inf_nan=False,
        description="Maximum JSON trace sampling target [Hz].",
    )
    report_workers: int = Field(default=1, gt=0, description="Concurrent API report/export jobs.")
    experiment_workers: int = Field(default=1, gt=0, description="Concurrent API experiment jobs.")
    experiment_max_cells: int = Field(
        default=128, gt=0, description="Maximum planned strategy/seed cells per API experiment."
    )
    slice_cache_size: int = Field(
        default=32, gt=0, description="Cached risk slices per API process."
    )
    slice_timeout_s: float = Field(
        default=30.0, gt=0, description="Risk slice computation timeout [s]."
    )
    max_upload_mb: int = Field(default=10, gt=0, description="Maximum request body size [MB].")
    page_limit_default: int = Field(default=50, gt=0, description="Default page size [items].")
    page_limit_max: int = Field(default=500, gt=0, description="Maximum page size [items].")
    sse: SseSettings = Field(default_factory=SseSettings)
    idempotency_ttl_s: int = Field(
        default=86400, gt=0, description="Retention of idempotency keys [s]."
    )
    error_type_base: str = Field(
        default=_DEFAULT_ERROR_TYPE_BASE,
        min_length=1,
        description="Base URL for RFC 9457 problem `type` links (docs/errors.md anchors).",
    )
    cursor_secret: SecretStr = Field(
        default=SecretStr(_DEFAULT_CURSOR_SECRET),
        description=(
            "HMAC key for opaque pagination cursors. Override in production so cursors survive "
            "process restarts; the committed default is for local/dev only."
        ),
    )

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.page_limit_default > self.page_limit_max:
            msg = "api.page_limit_default must not exceed api.page_limit_max"
            raise ValueError(msg)
        if self.token is None and not is_loopback_host(self.host):
            msg = f"api.token is required when api.host is not loopback (got {self.host!r})"
            raise ValueError(msg)
        return self


def is_loopback_host(host: str) -> bool:
    """Return whether ``host`` only accepts local connections.

    Args:
        host: Host name or IP literal (IPv6 may be bracketed).

    Returns:
        ``True`` for ``localhost`` and loopback IPs, ``False`` otherwise (incl. ``0.0.0.0``).
    """
    if host.lower() in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False
