"""HTTP API settings (docs/27 §4.3).

Layer: Kernel (L1).
"""

import ipaddress
from typing import Self

from pydantic import Field, SecretStr, model_validator

from roboprobe.core.settings._base import PORT_MAX, SettingsSection

__all__ = ["ApiSettings", "SseSettings"]

_LOOPBACK_NAMES = frozenset({"localhost"})


class SseSettings(SettingsSection):
    """Server-sent events stream settings."""

    ping_interval_s: float = Field(
        default=15.0, gt=0, description="Keep-alive ping interval on SSE streams [s]."
    )


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
    max_upload_mb: int = Field(default=10, gt=0, description="Maximum request body size [MB].")
    page_limit_default: int = Field(default=50, gt=0, description="Default page size [items].")
    page_limit_max: int = Field(default=500, gt=0, description="Maximum page size [items].")
    sse: SseSettings = Field(default_factory=SseSettings)
    idempotency_ttl_s: int = Field(
        default=86400, gt=0, description="Retention of idempotency keys [s]."
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
