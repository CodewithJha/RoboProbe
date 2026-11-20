"""Multi-campaign orchestrator supervisor (docs/05 §5.1).

Discovers RUNNING campaigns, drives up to ``runner.max_concurrent_campaigns``
:class:`~roboprobe.runner.loop.CampaignLoop` instances (one thread each), schedules the
reaper, and exposes ``/healthz`` (last tick age) plus queue-depth metrics.

Layer: Application (L3).

Implements: T-048, FR-RUN-001, NFR-REL-002
"""

from __future__ import annotations

import importlib
import threading
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID

import structlog

from roboprobe.core.clock import Clock
from roboprobe.core.errors import RoboProbeError
from roboprobe.core.health import Check, HealthServer, serve_health
from roboprobe.core.metrics_registry import Metrics
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import CampaignStatus, RunStatus
from roboprobe.runner.lifecycle import CampaignService
from roboprobe.runner.loop import CampaignLoop
from roboprobe.runner.ports import UowFactory
from roboprobe.runner.reaper import Reaper
from roboprobe.runner.scheduler import Scheduler
from roboprobe.runner.stop_rules import counters_from_runs, evaluate_stop_rules
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.selection.base import StrategyContext
from roboprobe.selection.registry import create as create_strategy

__all__ = ["Orchestrator"]

log = structlog.get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_TERMINAL = frozenset(
    {
        CampaignStatus.COMPLETED,
        CampaignStatus.FAILED,
        CampaignStatus.CANCELLED,
        CampaignStatus.PAUSED,
    }
)
_TICK_AGE_FACTOR = 5


class _Lock(Protocol):
    def release(self) -> None: ...


@dataclass
class _CampaignWorker:
    campaign_id: UUID
    thread: threading.Thread
    stop: threading.Event
    lock: _Lock


@dataclass
class Orchestrator:
    """Long-running supervisor over RUNNING campaigns."""

    settings: RoboProbeSettings
    uow_factory: UowFactory
    clock: Clock
    metrics: Metrics
    campaigns: CampaignService
    reaper: Reaper
    scheduler: Scheduler
    engine: object
    space_root: Path = field(default_factory=lambda: _REPO_ROOT)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _last_tick: datetime | None = field(default=None, init=False)
    _active: dict[UUID, _CampaignWorker] = field(default_factory=dict, init=False)
    _health: HealthServer | None = field(default=None, init=False)
    _guard: threading.Lock = field(default_factory=threading.Lock, init=False)

    @property
    def last_tick_at(self) -> datetime | None:
        """Wall time of the last supervisor tick (``None`` before the first)."""
        return self._last_tick

    def serve_forever(self, stop: threading.Event | None = None) -> None:
        """Run the supervisor until ``stop`` is set (or :meth:`request_stop`)."""
        external = stop if stop is not None else threading.Event()
        self._stop.clear()
        self._health = serve_health(
            self.settings.worker.health_host,
            self.settings.worker.health_port,
            [Check(name="tick", probe=self._health_probe)],
            self.metrics,
        )
        try:
            while not external.is_set() and not self._stop.is_set():
                self.tick()
                self.clock.sleep(self.settings.runner.tick_interval_s)
        finally:
            self._shutdown_campaigns()
            if self._health is not None:
                self._health.stop()
                self._health = None

    def request_stop(self) -> None:
        """Signal the supervisor loop to exit."""
        self._stop.set()

    def tick(self) -> None:
        """One supervisor tick: discover campaigns, reap, refresh metrics."""
        self._last_tick = self.clock.now()
        self._reap_if_due()
        self._refresh_queue_depth()
        self._prune_finished()
        running = self._list_running()
        with self._guard:
            capacity = self.settings.runner.max_concurrent_campaigns - len(self._active)
            for campaign_id in running:
                if capacity <= 0:
                    break
                if campaign_id in self._active:
                    continue
                if self._start_campaign(campaign_id):
                    capacity -= 1

    def _start_campaign(self, campaign_id: UUID) -> bool:
        locks = importlib.import_module("roboprobe.store.locks")
        lock_obj = locks.AdvisoryLock(self.engine, locks.campaign_lock_key(campaign_id))
        if not lock_obj.acquire():
            return False
        lock = cast("_Lock", lock_obj)
        stop = threading.Event()
        thread = threading.Thread(
            target=self._drive_campaign,
            args=(campaign_id, stop, lock),
            name=f"campaign-{campaign_id}",
            daemon=True,
        )
        self._active[campaign_id] = _CampaignWorker(
            campaign_id=campaign_id, thread=thread, stop=stop, lock=lock
        )
        thread.start()
        with suppress(ValueError):
            # structlog may hit a closed capture stream under CliRunner.
            log.info("orchestrator.campaign_started", campaign_id=str(campaign_id))
        return True

    def _drive_campaign(self, campaign_id: UUID, stop: threading.Event, lock: _Lock) -> None:
        try:
            self._run_campaign_loop(campaign_id, stop)
        except Exception as exc:
            reason = type(exc).__name__
            if isinstance(exc, RoboProbeError):
                reason = str(exc) or reason
            log.info(
                "orchestrator.campaign_failed",
                campaign_id=str(campaign_id),
                reason=reason,
            )
            try:
                self.campaigns.fail(campaign_id, reason=reason)
            except Exception:
                log.info("orchestrator.fail_status_error", campaign_id=str(campaign_id))
        finally:
            lock.release()
            with self._guard:
                self._active.pop(campaign_id, None)

    def _run_campaign_loop(self, campaign_id: UUID, stop: threading.Event) -> None:
        with self.uow_factory() as uow:
            campaign = uow.campaigns.get(campaign_id)
            if campaign is None:
                return
        space_yaml = self.space_root / "configs" / "scenario_spaces" / f"{campaign.space_id}.yaml"
        space = ScenarioSpace.from_yaml(space_yaml, base_dir=self.space_root)
        ctx = StrategyContext(
            space=space,
            budget=campaign.budget,
            seed=campaign.seed,
            batch_size=campaign.batch_size,
            params=dict(campaign.strategy_params),
        )
        strategy = create_strategy(campaign.strategy_id, ctx)
        loop = CampaignLoop(
            campaign_id,
            uow_factory=self.uow_factory,
            settings=self.settings.runner,
            selection=self.settings.selection,
            space=space,
            strategy=strategy,
            scheduler=self.scheduler,
            clock=self.clock,
            metrics=self.metrics,
        )
        while not stop.is_set() and not self._stop.is_set():
            with self.uow_factory() as uow:
                current = uow.campaigns.get(campaign_id)
                if current is None or current.status in _TERMINAL:
                    return
                if current.status is not CampaignStatus.RUNNING:
                    self.clock.sleep(self.settings.runner.tick_interval_s)
                    continue
                runs = _load_runs(uow, campaign_id)
                counters = counters_from_runs(
                    budget=current.budget,
                    runs=runs,  # type: ignore[arg-type]
                    modes_found=0,
                    started_at=current.started_at,
                    now=self.clock.now(),
                    stop_rules=dict(current.stop_rules),
                )
                decision = evaluate_stop_rules(counters, self.settings.runner)
            if decision.action == "analyze":
                self.campaigns.mark_analyzing(campaign_id, reason=decision.reason)
                self.campaigns.complete(campaign_id, reason=decision.reason)
                return
            if decision.action == "pause":
                self.campaigns.pause(campaign_id, reason=decision.reason)
                return
            loop.step()
            self.clock.sleep(self.settings.runner.tick_interval_s)

    def _list_running(self) -> list[UUID]:
        ids: list[UUID] = []
        cursor = None
        with self.uow_factory() as uow:
            while True:
                page = cast("Any", uow.campaigns.list(limit=None, cursor=cursor))
                for campaign in page.items:
                    if campaign.status is CampaignStatus.RUNNING:
                        ids.append(campaign.id)
                cursor = page.next_cursor
                if cursor is None:
                    break
        return ids

    def _prune_finished(self) -> None:
        with self._guard:
            finished = [cid for cid, worker in self._active.items() if not worker.thread.is_alive()]
            for cid in finished:
                self._active.pop(cid, None)

    def _shutdown_campaigns(self) -> None:
        with self._guard:
            workers = list(self._active.values())
        for worker in workers:
            worker.stop.set()
        for worker in workers:
            worker.thread.join(timeout=self.settings.worker.drain_timeout_s)
            # Thread ``finally`` releases the advisory lock; only force-release if join timed out.
            if worker.thread.is_alive():
                worker.lock.release()
        with self._guard:
            self._active.clear()

    def _reap_if_due(self) -> None:
        if self.reaper.due(self.clock.now()):
            self.reaper.reap(self.clock.now())

    def _refresh_queue_depth(self) -> None:
        if not self.metrics.enabled:
            return
        depths: dict[str, int] = {}
        cursor = None
        with self.uow_factory() as uow:
            while True:
                page = cast("Any", uow.campaigns.list(limit=None, cursor=cursor))
                for campaign in page.items:
                    runs_cursor = None
                    while True:
                        runs = cast(
                            "Any",
                            uow.runs.list_for_campaign(campaign.id, limit=None, cursor=runs_cursor),
                        )
                        for run in runs.items:
                            status = RunStatus(str(getattr(run.status, "value", run.status)))
                            if status is RunStatus.PENDING:
                                depths[run.backend] = depths.get(run.backend, 0) + 1
                        runs_cursor = runs.next_cursor
                        if runs_cursor is None:
                            break
                cursor = page.next_cursor
                if cursor is None:
                    break
        for backend, depth in depths.items():
            self.metrics.queue_depth.labels(backend=backend).set(depth)

    def _health_probe(self) -> None:
        if self._last_tick is None:
            msg = "orchestrator has not ticked yet"
            raise RuntimeError(msg)
        age = (self.clock.now() - self._last_tick).total_seconds()
        limit = self.settings.runner.tick_interval_s * _TICK_AGE_FACTOR
        if age > limit:
            msg = f"last tick age {age:.1f}s exceeds {limit:.1f}s"
            raise RuntimeError(msg)


def _load_runs(uow: object, campaign_id: UUID) -> list[object]:
    runs: list[object] = []
    cursor = None
    while True:
        page = uow.runs.list_for_campaign(campaign_id, limit=None, cursor=cursor)  # type: ignore[attr-defined]
        runs.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    return runs
