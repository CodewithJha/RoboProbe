"""Reaper: re-queue stale CLAIMED/RUNNING runs and mark dead workers OFFLINE.

Implements: T-042a, FR-RUN-002
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

import structlog

from roboprobe.core.clock import Clock
from roboprobe.core.settings.runner import RunnerSettings
from roboprobe.runner.ports import RunQueuePort, UowFactory

__all__ = ["Reaper", "next_reap_due"]

log = structlog.get_logger(__name__)

TOPIC_WORKER_UPDATED: Final = "worker.updated"
WORKER_OFFLINE: Final = "OFFLINE"


def next_reap_due(now: datetime, interval_s: float) -> datetime:
    """Return ``now + interval_s`` (pure helper for fake-clock tests)."""
    return now + timedelta(seconds=interval_s)


class Reaper:
    """Calls ``RunQueue.reap`` and marks workers with stale heartbeats ``OFFLINE``."""

    def __init__(
        self,
        *,
        queue: RunQueuePort,
        uow_factory: UowFactory,
        settings: RunnerSettings,
        clock: Clock,
    ) -> None:
        """Inject queue, UoW factory, runner settings and clock."""
        self._queue = queue
        self._uow_factory = uow_factory
        self._settings = settings
        self._clock = clock
        self._next_due = clock.now()

    def reap(self, now: datetime | None = None) -> int:
        """Re-queue/fail stale runs; return how many runs were touched."""
        at = now if now is not None else self._clock.now()
        n = self._queue.reap(at, self._settings.heartbeat_timeout_s, self._settings.max_attempts)
        if n:
            log.info("run.requeued", count=n, at=at.isoformat())
        self._mark_offline_workers(at)
        self._next_due = next_reap_due(at, self._settings.reaper_interval_s)
        return n

    def due(self, now: datetime | None = None) -> bool:
        """Whether a reap sweep should run."""
        at = now if now is not None else self._clock.now()
        return at >= self._next_due

    def _mark_offline_workers(self, now: datetime) -> None:
        older_than = now - timedelta(seconds=self._settings.heartbeat_timeout_s)
        with self._uow_factory() as uow:
            for worker in uow.workers.stale(older_than=older_than):
                uow.workers.set_status(worker.id, WORKER_OFFLINE, current_run_id=None)
                uow.events.append(
                    TOPIC_WORKER_UPDATED,
                    {
                        "worker_id": worker.id,
                        "status": WORKER_OFFLINE,
                        "last_heartbeat": (
                            None
                            if worker.last_heartbeat is None
                            else worker.last_heartbeat.isoformat()
                        ),
                    },
                )
            uow.commit()
