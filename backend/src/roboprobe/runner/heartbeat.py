"""Worker heartbeat thread, registration and status updates.

Implements: T-040b, FR-RUN-002, NFR-REL-001
"""

from __future__ import annotations

import importlib
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Final
from uuid import UUID

import structlog

from roboprobe import __version__
from roboprobe.core.clock import Clock
from roboprobe.core.health import Check, HealthServer, serve_health
from roboprobe.core.metrics_registry import Metrics, create_metrics
from roboprobe.core.settings.runner import RetrySettings
from roboprobe.core.settings.worker import WorkerSettings
from roboprobe.core.types import JsonValue
from roboprobe.runner.ports import UowFactory
from roboprobe.runner.worker import WORKER_BUSY, WORKER_DRAINING, WORKER_IDLE, WorkerProcess

__all__ = ["HeartbeatService", "WorkerRegistration"]

log = structlog.get_logger(__name__)

TOPIC_WORKER_UPDATED: Final = "worker.updated"


class WorkerRegistration:
    """Identity and capabilities written to the ``workers`` table."""

    def __init__(
        self,
        worker_id: str,
        backend: str,
        *,
        capabilities: dict[str, JsonValue] | None = None,
        version: str | None = None,
    ) -> None:
        """Build registration fields for the workers table."""
        self.worker_id = worker_id
        self.backend = backend
        self.capabilities = capabilities or {}
        self.version = version if version is not None else __version__


class HeartbeatService:
    """Background heartbeat with its own UoW sessions (never shared across threads)."""

    def __init__(  # noqa: PLR0913 - heartbeat collaborators are explicit seams
        self,
        *,
        worker: WorkerProcess,
        uow_factory: UowFactory,
        clock: Clock,
        settings: WorkerSettings,
        retry: RetrySettings,
        heartbeat_timeout_s: float,
        metrics: Metrics | None = None,
        record_factory: Callable[[str, str, str, dict[str, JsonValue]], object] | None = None,
    ) -> None:
        """Wire worker, UoW factory, clock, settings and optional record factory."""
        self._worker = worker
        self._uow_factory = uow_factory
        self._clock = clock
        self._settings = settings
        self._retry = retry
        self._heartbeat_timeout_s = heartbeat_timeout_s
        self._metrics = metrics if metrics is not None else create_metrics(enabled=False)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._health: HealthServer | None = None
        self._last_ok: datetime | None = None
        self._failures = 0
        self._record_factory = record_factory or _default_worker_record

    @property
    def last_heartbeat(self) -> datetime | None:
        """Wall time of the last successful heartbeat."""
        return self._last_ok

    def register(self) -> None:
        """Insert/upsert the worker row as ``IDLE``."""
        if self._settings.backend is None:
            msg = "worker.backend is required"
            raise ValueError(msg)
        caps = _capabilities(self._worker.backend)
        record = self._record_factory(
            self._worker.worker_id, self._settings.backend, __version__, caps
        )
        with self._uow_factory() as uow:
            uow.workers.register(record)
            uow.events.append(
                TOPIC_WORKER_UPDATED,
                {
                    "worker_id": self._worker.worker_id,
                    "status": WORKER_IDLE,
                    "last_heartbeat": self._clock.now().isoformat(),
                },
            )
            uow.commit()
        self._beat_once()

    def start(self) -> None:
        """Start the heartbeat thread and optional health server."""
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name=f"heartbeat-{self._worker.worker_id}", daemon=True
        )
        self._thread.start()
        self._health = serve_health(
            self._settings.health_host,
            self._settings.health_port,
            [Check(name="heartbeat", probe=self._health_probe)],
            self._metrics,
        )

    def stop(self) -> None:
        """Stop the heartbeat thread and health server."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._settings.heartbeat_join_timeout_s)
            self._thread = None
        if self._health is not None:
            self._health.stop()
            self._health = None

    def _loop(self) -> None:
        while not self._stop.wait(self._settings.heartbeat_interval_s):
            try:
                self._beat_once()
                self._failures = 0
            except Exception:
                self._failures += 1
                delay = min(
                    self._retry.base_delay_s * (2 ** (self._failures - 1)),
                    self._retry.max_delay_s,
                )
                self._clock.sleep(delay)

    def _beat_once(self) -> None:
        at = self._clock.now()
        run_id = self._worker.current_run_id
        status = WORKER_BUSY if run_id is not None else WORKER_IDLE
        if self._worker.is_draining:
            status = WORKER_DRAINING
        with self._uow_factory() as uow:
            uow.workers.heartbeat(self._worker.worker_id, at=at)
            uow.workers.set_status(self._worker.worker_id, status, current_run_id=run_id)
            uow.events.append(
                TOPIC_WORKER_UPDATED,
                {
                    "worker_id": self._worker.worker_id,
                    "status": status,
                    "last_heartbeat": at.isoformat(),
                },
            )
            uow.commit()
        self._last_ok = at

    def _health_probe(self) -> None:
        if self._last_ok is None:
            msg = "no heartbeat yet"
            raise RuntimeError(msg)
        age = (self._clock.now() - self._last_ok).total_seconds()
        if age > self._heartbeat_timeout_s:
            msg = f"heartbeat stale ({age:.1f}s)"
            raise RuntimeError(msg)


def _capabilities(backend: object) -> dict[str, JsonValue]:
    caps = getattr(backend, "capabilities", None)
    if caps is None:
        return {}
    name = getattr(caps, "name", "")
    return {"name": str(name), "deterministic": bool(getattr(caps, "deterministic", False))}


def _default_worker_record(
    worker_id: str, backend: str, version: str, capabilities: dict[str, JsonValue]
) -> object:
    mod = importlib.import_module("roboprobe.store.records")
    return mod.WorkerRecord(
        id=worker_id,
        backend=backend,
        status=WORKER_IDLE,
        capabilities=capabilities,
        version=version,
    )


# UUID kept for type docs.
_ = UUID
