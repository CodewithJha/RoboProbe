"""Logging and observability settings (docs/27 §4.10, docs/21).

Layer: Kernel (L1).
"""

from typing import Literal

from pydantic import AnyHttpUrl, Field

from roboprobe.core.settings._base import SettingsSection

__all__ = ["LogFormat", "LogLevel", "LoggingSettings", "ObservabilitySettings"]

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LogFormat = Literal["json", "console"]


class LoggingSettings(SettingsSection):
    """structlog output settings (docs/34 §6)."""

    level: LogLevel = Field(default="INFO", description="Minimum log level.")
    format: LogFormat = Field(
        default="json", description="`json` (prod/ci) or `console` (human-readable local output)."
    )
    include_caller: bool = Field(default=False, description="Add module/function/line to logs.")


class ObservabilitySettings(SettingsSection):
    """Metrics and tracing settings."""

    metrics_enabled: bool = Field(default=True, description="Expose Prometheus metrics.")
    otlp_endpoint: AnyHttpUrl | None = Field(
        default=None, description="OTLP collector URL; tracing is off when unset."
    )
    service_name: str | None = Field(
        default=None,
        min_length=1,
        description="Service name in logs/traces; derived per process (`roboprobe-api`, ...).",
    )
