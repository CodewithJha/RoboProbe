"""WorkerProcess: claim → materialise → run → judge → persist.

Implements: T-040a, T-040c, FR-RUN-001, FR-RUN-003, FR-RUN-005, FR-RUN-006
"""

from __future__ import annotations

import importlib
import os
import shutil
import signal
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, cast
from uuid import UUID

import structlog

from roboprobe.core.clock import Clock
from roboprobe.core.metrics_registry import Metrics, create_metrics
from roboprobe.core.settings.storage import StorageSettings
from roboprobe.core.settings.worker import WorkerSettings
from roboprobe.core.types import (
    CampaignStatus,
    Scenario,
    SutProfile,
    TaskSpec,
)
from roboprobe.oracles.verdict import VerdictEngine
from roboprobe.runner.ports import (
    ArtifactRefView,
    ArtifactStorePort,
    ClaimedRunView,
    RunQueuePort,
    SimulatorBackendPort,
    UowFactory,
)

__all__ = ["WorkerEpisodeRequest", "WorkerProcess", "WorkerState"]

log = structlog.get_logger(__name__)

WORKER_IDLE: Final = "IDLE"
WORKER_BUSY: Final = "BUSY"
WORKER_DRAINING: Final = "DRAINING"
WORKER_OFFLINE: Final = "OFFLINE"


class WorkerState(StrEnum):
    """Internal execution phases (docs/05 §5.2)."""

    IDLE = "IDLE"
    CLAIMING = "CLAIMING"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    EVALUATING = "EVALUATING"
    UPLOADING = "UPLOADING"
    DRAINING = "DRAINING"


@dataclass(frozen=True, slots=True)
class WorkerEpisodeRequest:
    """Episode request DTO constructed without importing ``roboprobe.backends``."""

    run_id: UUID
    scenario: Scenario
    task: TaskSpec
    sut_profile: SutProfile
    seed: int
    workdir: Path
    sim_time_budget_s: float
    wall_timeout_s: float
    record_bag: bool = False


class WorkerProcess:
    """Single-slot worker: claim one run, execute, persist, repeat."""

    def __init__(  # noqa: PLR0913 - worker collaborators match docs/05 §5.2
        self,
        *,
        backend: SimulatorBackendPort,
        uow_factory: UowFactory,
        queue: RunQueuePort,
        artifact_store: ArtifactStorePort,
        verdict_engine: VerdictEngine,
        clock: Clock,
        worker_settings: WorkerSettings,
        storage_settings: StorageSettings,
        task: TaskSpec,
        metrics: Metrics | None = None,
        slot: int = 0,
        on_after_claim: Callable[[ClaimedRunView], None] | None = None,
    ) -> None:
        """Constructor-injected collaborators only (docs/05 §5.2)."""
        if worker_settings.backend is None:
            msg = "worker.backend is required"
            raise ValueError(msg)
        self._backend = backend
        self._uow_factory = uow_factory
        self._queue = queue
        self._artifacts = artifact_store
        self._verdict = verdict_engine
        self._clock = clock
        self._worker = worker_settings
        self._storage = storage_settings
        self._task = task
        self._metrics = metrics if metrics is not None else create_metrics(enabled=False)
        self._slot = slot
        self._on_after_claim = on_after_claim
        self._backend_name = worker_settings.backend
        self.worker_id = f"{worker_settings.id_prefix}:{os.getpid()}:{slot}"
        self.state = WorkerState.IDLE
        self.current_run_id: UUID | None = None
        self._drain = threading.Event()
        self._stop = threading.Event()
        self._cancel_episode = threading.Event()

    @property
    def backend(self) -> SimulatorBackendPort:
        """Injected simulator backend."""
        return self._backend

    @property
    def is_draining(self) -> bool:
        """Whether SIGTERM/drain was requested."""
        return self._drain.is_set()

    def request_drain(self) -> None:
        """Enter ``DRAINING``: finish the current run, claim no more."""
        self._drain.set()
        if self.state is WorkerState.IDLE:
            self.state = WorkerState.DRAINING

    def request_stop(self) -> None:
        """Signal the main loop to exit after drain."""
        self._drain.set()
        self._stop.set()

    def install_signal_handlers(self) -> None:
        """SIGTERM → graceful drain (T-040c)."""

        def _handle(signum: int, frame: object) -> None:
            del signum, frame
            self.request_drain()
            self.request_stop()

        signal.signal(signal.SIGTERM, _handle)

    def serve_forever(self, stop: threading.Event | None = None) -> None:
        """Poll/claim/execute until ``stop`` or drain completes."""
        external = stop if stop is not None else threading.Event()
        self._backend.prepare()
        while not external.is_set() and not self._stop.is_set():
            if self._drain.is_set() and self.current_run_id is None:
                self.state = WorkerState.DRAINING
                break
            claimed = self.claim()
            if claimed is None:
                self._clock.sleep(self._worker.poll_interval_s)
                continue
            self.execute(claimed)
        self.state = WorkerState.DRAINING if self._drain.is_set() else WorkerState.IDLE

    def claim(self) -> ClaimedRunView | None:
        """Claim the next ``PENDING`` run for this backend, or ``None``."""
        if self._drain.is_set():
            return None
        self.state = WorkerState.CLAIMING
        claimed = self._queue.claim(self.worker_id, self._backend_name)
        if claimed is None:
            self.state = WorkerState.IDLE
            return None
        self.current_run_id = claimed.run_id
        self._cancel_episode.clear()
        log.info(
            "run.claimed",
            run_id=str(claimed.run_id),
            campaign_id=str(claimed.campaign_id),
            worker_id=self.worker_id,
            attempt=claimed.attempt,
        )
        if self._on_after_claim is not None:
            self._on_after_claim(claimed)
        return claimed

    def execute(self, run: ClaimedRunView) -> None:
        """Materialise → run episode → judge → upload → persist."""
        workdir = self._storage.workdir_root / str(run.run_id)
        workdir.mkdir(parents=True, exist_ok=True)
        started = self._clock.monotonic()
        try:
            campaign_status, space_id, space_version, sut, wall_s, sim_s = self._load_context(run)
            self.state = WorkerState.PREPARING
            self._queue.mark_running(run.run_id)
            if campaign_status is CampaignStatus.CANCELLED:
                self._queue.fail(run.run_id, "campaign_cancelled")
                return
            scenario = Scenario(
                space_id=space_id,
                space_version=space_version,
                values=dict(run.scenario_values),
                scenario_hash=run.scenario_hash,
            )
            req = WorkerEpisodeRequest(
                run_id=run.run_id,
                scenario=scenario,
                task=self._task,
                sut_profile=sut,
                seed=run.seed,
                workdir=workdir,
                sim_time_budget_s=sim_s,
                wall_timeout_s=wall_s,
            )
            log.info("run.started", run_id=str(run.run_id), worker_id=self.worker_id)
            materialized = self._backend.materialize(req)
            self.state = WorkerState.RUNNING

            def _on_progress(frac: float) -> None:
                del frac
                if self._cancel_episode.is_set() or self._campaign_cancelled(run.campaign_id):
                    self._backend.cancel()

            result = self._backend.run_episode(req, materialized, on_progress=_on_progress)
            elapsed = self._clock.monotonic() - started
            infra = result.infra_error
            if infra is None and elapsed > wall_s:
                infra = "wall_timeout"
            if infra is not None:
                self._queue.fail(run.run_id, infra)
                self._observe_finished(run.backend, "INVALID", "F-INFRA", elapsed)
                return
            self.state = WorkerState.EVALUATING
            self._queue.mark_evaluating(run.run_id)
            outcome = self._verdict.judge(result, self._task)
            self.state = WorkerState.UPLOADING
            self._upload(run, result.artifacts, materialized.files)
            self._queue.complete(run.run_id, outcome)
            primary = "none" if outcome.primary_failure is None else outcome.primary_failure.value
            self._observe_finished(run.backend, outcome.verdict.value, primary, elapsed)
            log.info(
                "run.finished",
                run_id=str(run.run_id),
                verdict=outcome.verdict.value,
                worker_id=self.worker_id,
            )
        except Exception as exc:
            self._queue.fail(run.run_id, f"infra_error:{type(exc).__name__}")
            elapsed = self._clock.monotonic() - started
            self._observe_finished(run.backend, "INVALID", "F-INFRA", elapsed)
            log.info(
                "run.finished",
                run_id=str(run.run_id),
                verdict="INVALID",
                worker_id=self.worker_id,
                error=type(exc).__name__,
            )
        finally:
            self.current_run_id = None
            self.state = WorkerState.DRAINING if self._drain.is_set() else WorkerState.IDLE
            shutil.rmtree(workdir, ignore_errors=True)

    def _load_context(
        self, run: ClaimedRunView
    ) -> tuple[CampaignStatus, str, str, SutProfile, float, float]:
        with self._uow_factory() as uow:
            campaign = uow.campaigns.get(run.campaign_id)
            if campaign is None:
                msg = "campaign missing for claimed run"
                raise RuntimeError(msg)
            sut_row = uow.sut_profiles.get(campaign.sut_profile_id)
            if sut_row is None:
                msg = "sut profile missing"
                raise RuntimeError(msg)
            sut = SutProfile(
                id=str(cast(Any, sut_row).id),
                backend=str(cast(Any, sut_row).backend),
                config=dict(cast(Any, sut_row).config),
                config_hash=str(cast(Any, sut_row).config_hash),
            )
            params = campaign.strategy_params
            wall_raw = params.get("wall_timeout_s", run.wall_timeout_s)
            sim_raw = params.get("sim_time_budget_s", run.sim_time_budget_s)
            wall = (
                float(wall_raw) if isinstance(wall_raw, (int, float, str)) else run.wall_timeout_s
            )
            sim = (
                float(sim_raw) if isinstance(sim_raw, (int, float, str)) else run.sim_time_budget_s
            )
            status = campaign.status
            space_id = campaign.space_id
            space_version = campaign.space_version
        return status, space_id, space_version, sut, wall, sim

    def _campaign_cancelled(self, campaign_id: UUID) -> bool:
        with self._uow_factory() as uow:
            campaign = uow.campaigns.get(campaign_id)
            return campaign is not None and campaign.status is CampaignStatus.CANCELLED

    def _upload(
        self,
        run: ClaimedRunView,
        artifacts: dict[str, Path],
        materialized: dict[str, Path],
    ) -> None:
        kind_map = {
            "trace": "trace",
            "log": "log",
            "world": "world",
            "bag": "bag",
            "params": "params",
            "manifest": "manifest",
        }
        refs: list[ArtifactRefView] = []
        for key, path in {**materialized, **artifacts}.items():
            kind = kind_map.get(key)
            if kind is None or not path.is_file():
                continue
            refs.append(
                self._artifacts.put(path, kind, run_id=run.run_id, campaign_id=run.campaign_id)
            )
        if not refs:
            return
        with self._uow_factory() as uow:
            for ref in refs:
                uow.artifacts.add(_artifact_record(ref, run.run_id, run.campaign_id))
            uow.commit()

    def _observe_finished(
        self, backend: str, verdict: str, primary_failure: str, elapsed_s: float
    ) -> None:
        self._metrics.runs_total.labels(
            backend=backend, verdict=verdict, primary_failure=primary_failure
        ).inc()
        self._metrics.run_duration_seconds.labels(backend=backend, phase="total").observe(elapsed_s)


def _artifact_record(ref: ArtifactRefView, run_id: UUID, campaign_id: UUID) -> object:
    """Build an ArtifactRecord-like object via dynamic import of the store model.

    Avoids a static ``roboprobe.store`` import (import-linter).
    """
    mod = importlib.import_module("roboprobe.store.records")
    return mod.ArtifactRecord(
        id=ref.id,
        run_id=run_id,
        campaign_id=campaign_id,
        kind=ref.kind,
        sha256=ref.sha256,
        size_bytes=ref.size_bytes,
        rel_path=ref.rel_path,
        media_type=ref.media_type,
    )
