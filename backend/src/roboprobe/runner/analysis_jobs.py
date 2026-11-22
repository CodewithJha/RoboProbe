"""Background campaign analysis jobs (incremental, post-campaign FULL, on-demand).

Implements: T-075b, FR-ANA-006
"""

from __future__ import annotations

import importlib
import threading
from collections.abc import Callable
from concurrent.futures import Executor, Future
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, cast
from uuid import UUID, uuid4

import structlog

from roboprobe.analysis.base import AnalysisKind, AnalysisReport
from roboprobe.analysis.pipeline import analyze_campaign
from roboprobe.analysis.ports import AnalysisArtifactStore, AnalysisUnitOfWork
from roboprobe.core.clock import Clock
from roboprobe.core.errors import ConflictError, ErrorCode
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import CampaignStatus
from roboprobe.runner.lifecycle import CampaignService
from roboprobe.runner.ports import CampaignView, UnitOfWorkPort, UowFactory
from roboprobe.scenario.space import ScenarioSpace

__all__ = ["AnalysisJobRunner"]

log = structlog.get_logger(__name__)

_TOPIC_ALERT: Final = "alert"
_ALERT_ANALYSIS_FAILED: Final = "ANALYSIS_FAILED"
_REPO_ROOT = Path(__file__).resolve().parents[4]


class _Releasable(Protocol):
    def release(self) -> None: ...


class _AdvisoryBusyError(Exception):
    """Advisory lock held elsewhere."""


@dataclass(slots=True)
class _LockSession:
    thread_lock: threading.Lock
    advisory: _Releasable | None


@dataclass(slots=True)
class _UowAdvisory:
    """Holds a UoW open for the lifetime of a port-level advisory lock."""

    uow: UnitOfWorkPort
    key: str

    def release(self) -> None:
        try:
            self.uow.advisory_unlock(self.key)
        finally:
            self.uow.__exit__(None, None, None)


class AnalysisJobRunner:
    """Enqueue analysis work without blocking the campaign orchestrator tick."""

    def __init__(  # noqa: PLR0913
        self,
        uow_factory: UowFactory,
        artifact_store: AnalysisArtifactStore | object,
        settings: RoboProbeSettings,
        executor: Executor,
        clock: Clock,
        *,
        campaigns: CampaignService | None = None,
        engine: object | None = None,
        space_root: Path | None = None,
        load_space: Callable[[str, str], ScenarioSpace] | None = None,
        analyze_fn: Callable[..., AnalysisReport] | None = None,
    ) -> None:
        """Wire persistence, artefacts, settings and a thread-pool executor."""
        self._uow_factory = uow_factory
        self._artifact_store = artifact_store
        self._settings = settings
        self._executor = executor
        self._clock = clock
        self._campaigns = campaigns
        self._engine = engine
        self._space_root = space_root if space_root is not None else _REPO_ROOT
        self._load_space = load_space or self._default_load_space
        self._analyze: Callable[..., AnalysisReport] = analyze_fn or analyze_campaign
        self._thread_locks: dict[UUID, threading.Lock] = {}
        self._guard = threading.Lock()
        self._incremental_at: dict[UUID, int] = {}
        self._inflight: set[UUID] = set()
        self._reserved: dict[UUID, UUID] = {}

    def on_campaign_status(self, campaign: CampaignView) -> None:
        """When a campaign enters ``ANALYZING``, schedule a FULL analysis → ``COMPLETED``."""
        if campaign.status is not CampaignStatus.ANALYZING:
            return
        self.schedule(campaign.id, AnalysisKind.FULL, complete_campaign=True)

    def on_run_finished(self, campaign_id: UUID, n_completed: int) -> None:
        """Fire incremental analysis every ``runner.analysis.incremental_every_n`` finished runs."""
        every = self._settings.runner.analysis.incremental_every_n
        if n_completed <= 0 or n_completed % every != 0:
            return
        with self._guard:
            if self._incremental_at.get(campaign_id) == n_completed:
                return
            self._incremental_at[campaign_id] = n_completed
        self.schedule(campaign_id, AnalysisKind.INCREMENTAL, complete_campaign=False)

    def schedule(
        self,
        campaign_id: UUID,
        kind: AnalysisKind,
        *,
        complete_campaign: bool = False,
        analysis_id: UUID | None = None,
    ) -> Future[UUID] | None:
        """Enqueue analysis; returns ``None`` when the per-campaign lock is already held."""
        with self._guard:
            if campaign_id in self._inflight:
                log.info(
                    "analysis.skipped",
                    campaign_id=str(campaign_id),
                    kind=kind.value,
                    reason="locked",
                )
                return None
            self._inflight.add(campaign_id)
        future = self._executor.submit(
            self._run,
            campaign_id,
            kind,
            complete_campaign,
            analysis_id,
        )
        future.add_done_callback(lambda _f: self._clear_inflight(campaign_id))
        return future

    def enqueue(self, campaign_id: UUID, kind: AnalysisKind) -> UUID:
        """Return a reserved analysis id immediately, reusing an in-flight API request."""
        with self._guard:
            if campaign_id in self._reserved:
                return self._reserved[campaign_id]
            if campaign_id in self._inflight:
                msg = "analysis already running for campaign"
                raise ConflictError(msg)
            analysis_id = uuid4()
            self._reserved[campaign_id] = analysis_id
            self._inflight.add(campaign_id)
        try:
            future = self._executor.submit(self._run, campaign_id, kind, False, analysis_id)
        except Exception:
            self._clear_inflight(campaign_id)
            raise
        future.add_done_callback(lambda _f: self._clear_inflight(campaign_id))
        return analysis_id

    def request(self, campaign_id: UUID, kind: AnalysisKind) -> UUID:
        """Run analysis synchronously (waits for the executor); raises if already locked."""
        future = self.schedule(campaign_id, kind, complete_campaign=False)
        if future is None:
            msg = "analysis already running for campaign"
            raise ConflictError(
                msg,
                code=ErrorCode.CAMPAIGN_INVALID_TRANSITION,
                context={"campaign_id": str(campaign_id)},
            )
        return future.result()

    def _run(
        self,
        campaign_id: UUID,
        kind: AnalysisKind,
        complete_campaign: bool,
        reserved_id: UUID | None = None,
    ) -> UUID:
        session = self._try_acquire(campaign_id)
        if session is None:
            msg = "analysis lock not acquired"
            raise RuntimeError(msg)
        reason: str | None = None
        analysis_id: UUID | None = None
        try:
            with self._uow_factory() as uow:
                report = self._analyze(
                    campaign_id,
                    cast(AnalysisUnitOfWork, uow),
                    cast(AnalysisArtifactStore, self._artifact_store),
                    kind=kind,
                    settings=self._settings.analysis,
                    risk=self._settings.risk,
                    clock=self._clock,
                    load_space=self._load_space,
                    **({"analysis_id": reserved_id} if reserved_id is not None else {}),
                )
                uow.commit()
            analysis_id = report.analysis_id
            if report.status == "ERROR":
                reason = "analysis ERROR"
                self._emit_analysis_failed(campaign_id, reason)
        except Exception as exc:
            reason = f"analysis failed: {type(exc).__name__}"
            log.warning(
                "analysis.failed",
                campaign_id=str(campaign_id),
                kind=kind.value,
                error=reason,
            )
            self._emit_analysis_failed(campaign_id, reason)
        finally:
            self._release(session)
        if complete_campaign and self._campaigns is not None:
            self._campaigns.complete(campaign_id, reason=reason)
        if analysis_id is None:
            msg = "analysis produced no id"
            raise RuntimeError(msg)
        return analysis_id

    def _clear_inflight(self, campaign_id: UUID) -> None:
        with self._guard:
            self._inflight.discard(campaign_id)
            self._reserved.pop(campaign_id, None)

    def _emit_analysis_failed(self, campaign_id: UUID, message: str) -> None:
        with self._uow_factory() as uow:
            uow.events.append(
                _TOPIC_ALERT,
                {
                    "level": "error",
                    "code": _ALERT_ANALYSIS_FAILED,
                    "message": message,
                    "campaign_id": str(campaign_id),
                },
                campaign_id=campaign_id,
            )
            uow.commit()

    def _try_acquire(self, campaign_id: UUID) -> _LockSession | None:
        thread_lock = self._thread_lock_for(campaign_id)
        if not thread_lock.acquire(blocking=False):
            return None
        try:
            advisory = self._try_pg_advisory(campaign_id)
        except _AdvisoryBusyError:
            thread_lock.release()
            return None
        return _LockSession(thread_lock=thread_lock, advisory=advisory)

    def _release(self, session: _LockSession) -> None:
        if session.advisory is not None:
            session.advisory.release()
        session.thread_lock.release()

    def _thread_lock_for(self, campaign_id: UUID) -> threading.Lock:
        with self._guard:
            lock = self._thread_locks.get(campaign_id)
            if lock is None:
                lock = threading.Lock()
                self._thread_locks[campaign_id] = lock
            return lock

    def _try_pg_advisory(self, campaign_id: UUID) -> _Releasable | None:
        key = f"analysis:{campaign_id}"
        if self._engine is not None:
            locks = importlib.import_module("roboprobe.store.locks")
            raw = locks.AdvisoryLock(self._engine, key)
            acquire = getattr(raw, "acquire", None)
            if not callable(acquire) or not bool(acquire()):
                raise _AdvisoryBusyError
            return cast(_Releasable, raw)
        uow = self._uow_factory()
        entered = uow.__enter__()
        if not entered.try_advisory_lock(key):
            entered.__exit__(None, None, None)
            raise _AdvisoryBusyError
        return _UowAdvisory(entered, key)

    def _default_load_space(self, space_id: str, version: str) -> ScenarioSpace:
        path = self._space_root / "configs" / "scenario_spaces" / f"{space_id}.yaml"
        return ScenarioSpace.from_yaml(path, base_dir=self._space_root)
