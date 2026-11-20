"""In-app alert evaluation (INFRA_UNHEALTHY, NO_WORKERS, DISK_LOW, GP_FALLBACK_REPEATED).

Implements: T-042b, NFR-OBS-001, docs/21 §5.5
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, Literal
from uuid import UUID

from roboprobe.core.settings.runner import RunnerSettings
from roboprobe.core.settings.storage import StorageSettings
from roboprobe.core.types import JsonValue

__all__ = [
    "ALERT_DISK_LOW",
    "ALERT_GP_FALLBACK_REPEATED",
    "ALERT_INFRA_UNHEALTHY",
    "ALERT_NO_WORKERS",
    "Alert",
    "AlertEvaluator",
]

ALERT_INFRA_UNHEALTHY: Final = "INFRA_UNHEALTHY"
ALERT_NO_WORKERS: Final = "NO_WORKERS"
ALERT_DISK_LOW: Final = "DISK_LOW"
ALERT_GP_FALLBACK_REPEATED: Final = "GP_FALLBACK_REPEATED"

TOPIC_ALERT: Final = "alert"
BYTES_PER_GIB: Final = 1024**3


@dataclass(frozen=True, slots=True)
class Alert:
    """One in-app alert payload (SSE ``alert`` event)."""

    level: Literal["info", "warning", "error"]
    code: str
    message: str
    campaign_id: UUID | None = None

    def payload(self) -> dict[str, JsonValue]:
        """JSON-safe event payload."""
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "campaign_id": None if self.campaign_id is None else str(self.campaign_id),
        }


class AlertEvaluator:
    """Evaluate infrastructure alert policies against live signals."""

    def __init__(
        self,
        runner: RunnerSettings,
        storage: StorageSettings,
        *,
        free_gb_probe: Callable[[Path], float] | None = None,
    ) -> None:
        """Bind runner/storage settings and an optional free-space probe."""
        self._runner = runner
        self._storage = storage
        self._free_gb = free_gb_probe or _disk_free_gb

    def no_workers(
        self,
        *,
        campaign_id: UUID,
        running_since: datetime | None,
        now: datetime,
        online_workers: int,
    ) -> Alert | None:
        """``NO_WORKERS`` when RUNNING with zero workers longer than the threshold."""
        if online_workers > 0 or running_since is None:
            return None
        age = (now - running_since).total_seconds()
        if age < self._runner.alerts.no_workers_after_s:
            return None
        return Alert(
            level="warning",
            code=ALERT_NO_WORKERS,
            message=f"No workers for {age:.0f}s",
            campaign_id=campaign_id,
        )

    def disk_low(self, *, root: Path | None = None) -> Alert | None:
        """``DISK_LOW`` when free space under ``storage.min_free_gb``."""
        path = root if root is not None else self._storage.artifact_root
        free = self._free_gb(path)
        if free >= self._storage.min_free_gb:
            return None
        return Alert(
            level="error",
            code=ALERT_DISK_LOW,
            message=f"Free disk {free:.2f} GiB < {self._storage.min_free_gb} GiB",
        )

    def gp_fallback_repeated(
        self, *, campaign_id: UUID, consecutive_fallbacks: int
    ) -> Alert | None:
        """``GP_FALLBACK_REPEATED`` after N consecutive selector fallbacks."""
        if consecutive_fallbacks < self._runner.alerts.gp_fallback_repeat:
            return None
        return Alert(
            level="warning",
            code=ALERT_GP_FALLBACK_REPEATED,
            message=f"{consecutive_fallbacks} consecutive selector fallbacks",
            campaign_id=campaign_id,
        )

    def infra_unhealthy(self, *, campaign_id: UUID, reason: str) -> Alert:
        """Build the auto-pause ``INFRA_UNHEALTHY`` alert."""
        return Alert(
            level="error",
            code=ALERT_INFRA_UNHEALTHY,
            message=reason,
            campaign_id=campaign_id,
        )


def _disk_free_gb(path: Path) -> float:
    path.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(path)
    return usage.free / BYTES_PER_GIB
