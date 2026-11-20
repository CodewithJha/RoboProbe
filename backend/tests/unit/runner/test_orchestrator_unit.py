"""Unit coverage for Orchestrator helpers (T-048)."""

from __future__ import annotations

import importlib
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from roboprobe.core.clock import FakeClock
from roboprobe.core.metrics_registry import create_metrics
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import CampaignStatus, RunStatus
from roboprobe.runner.lifecycle import CampaignService
from roboprobe.runner.orchestrator import Orchestrator, _CampaignWorker, _load_runs
from roboprobe.runner.reaper import Reaper
from roboprobe.runner.scheduler import Scheduler

pytestmark = pytest.mark.unit


class _Page:
    def __init__(self, items: list[object], next_cursor: str | None = None) -> None:
        self.items = items
        self.next_cursor = next_cursor


class _Runs:
    def __init__(self, runs: list[object]) -> None:
        self._runs = runs

    def list_for_campaign(
        self, campaign_id: object, *, limit: int | None = None, cursor: str | None = None
    ) -> _Page:
        del campaign_id, limit, cursor
        return _Page(self._runs)


class _Campaigns:
    def __init__(self, campaigns: list[object]) -> None:
        self._campaigns = campaigns

    def list(self, *, limit: int | None = None, cursor: str | None = None) -> _Page:
        del limit, cursor
        return _Page(self._campaigns)

    def get(self, campaign_id: object) -> object | None:
        for item in self._campaigns:
            if getattr(item, "id", None) == campaign_id:
                return item
        return None


class _Workers:
    def stale(self, *, older_than: object) -> list[object]:
        del older_than
        return []


class _Uow:
    def __init__(self, campaigns: _Campaigns, runs: _Runs) -> None:
        self.campaigns = campaigns
        self.runs = runs
        self.workers = _Workers()

    def __enter__(self) -> _Uow:
        return self

    def __exit__(self, *args: object) -> None:
        del args


def _settings() -> RoboProbeSettings:
    return RoboProbeSettings(
        observability={"metrics_enabled": True},
        runner={"tick_interval_s": 0.01, "reaper_interval_s": 10.0, "max_concurrent_campaigns": 2},
        worker={"health_host": "127.0.0.1", "health_port": 19102, "drain_timeout_s": 0.05},
    )


def _make_orch(campaigns: _Campaigns, runs: _Runs) -> Orchestrator:
    def uow_factory() -> _Uow:
        return _Uow(campaigns, runs)

    settings = _settings()
    clock = FakeClock(start=datetime(2020, 1, 1, tzinfo=UTC))
    metrics = create_metrics(enabled=True)
    queue = SimpleNamespace(reap=lambda *a, **k: 0, depth=lambda b: 0)
    return Orchestrator(
        settings=settings,
        uow_factory=uow_factory,  # type: ignore[arg-type]
        clock=clock,
        metrics=metrics,
        campaigns=CampaignService(uow_factory),  # type: ignore[arg-type]
        reaper=Reaper(
            queue=queue,  # type: ignore[arg-type]
            uow_factory=uow_factory,  # type: ignore[arg-type]
            settings=settings.runner,
            clock=clock,
        ),
        scheduler=Scheduler(settings.runner),
        engine=object(),
    )


def test_list_running_queue_depth_and_health() -> None:
    cid = uuid4()
    campaigns = _Campaigns(
        [
            SimpleNamespace(id=cid, status=CampaignStatus.RUNNING, backend="kinematic2d"),
            SimpleNamespace(id=uuid4(), status=CampaignStatus.COMPLETED, backend="kinematic2d"),
        ]
    )
    runs = _Runs(
        [
            SimpleNamespace(status=RunStatus.PENDING, backend="kinematic2d"),
            SimpleNamespace(status=RunStatus.DONE, backend="kinematic2d"),
        ]
    )
    orch = _make_orch(campaigns, runs)
    assert orch._list_running() == [cid]
    orch._refresh_queue_depth()
    with pytest.raises(RuntimeError, match="has not ticked"):
        orch._health_probe()
    orch._last_tick = orch.clock.now()
    orch._health_probe()
    orch._last_tick = orch.clock.now() - timedelta(seconds=10)
    with pytest.raises(RuntimeError, match="last tick age"):
        orch._health_probe()


def test_load_runs_paginates() -> None:
    uow = _Uow(_Campaigns([]), _Runs([SimpleNamespace(id=1), SimpleNamespace(id=2)]))
    assert len(_load_runs(uow, uuid4())) == 2


def test_request_stop_sets_event() -> None:
    orch = _make_orch(_Campaigns([]), _Runs([]))
    orch.request_stop()
    assert orch._stop.is_set()


def test_tick_starts_campaign_when_lock_held(monkeypatch: pytest.MonkeyPatch) -> None:
    cid = uuid4()
    campaigns = _Campaigns(
        [SimpleNamespace(id=cid, status=CampaignStatus.RUNNING, backend="kinematic2d")]
    )
    orch = _make_orch(campaigns, _Runs([]))
    started: list[UUID] = []

    class _Lock:
        def acquire(self) -> bool:
            return True

        def release(self) -> None: ...

    real_import = importlib.import_module

    def _import(name: str) -> object:
        if name == "roboprobe.store.locks":
            return SimpleNamespace(
                AdvisoryLock=lambda *_a, **_k: _Lock(),
                campaign_lock_key=lambda _c: "k",
            )
        return real_import(name)

    monkeypatch.setattr("roboprobe.runner.orchestrator.importlib.import_module", _import)
    monkeypatch.setattr(orch, "_drive_campaign", lambda c, *_a: started.append(c))
    monkeypatch.setattr(orch.reaper, "due", lambda _n: False)

    orch.tick()
    assert cid in orch._active
    orch._active[cid].thread.join(timeout=1.0)
    assert started == [cid]


def test_prune_finished_removes_dead_threads() -> None:
    orch = _make_orch(_Campaigns([]), _Runs([]))
    cid = uuid4()
    finished = threading.Thread(target=lambda: None)
    finished.start()
    finished.join()
    orch._active[cid] = _CampaignWorker(
        campaign_id=cid,
        thread=finished,
        stop=threading.Event(),
        lock=SimpleNamespace(release=lambda: None),
    )
    orch._prune_finished()
    assert cid not in orch._active


def test_shutdown_campaigns_stops_workers() -> None:
    orch = _make_orch(_Campaigns([]), _Runs([]))
    cid = uuid4()
    stop = threading.Event()

    def _wait(stop_ev: threading.Event) -> None:
        stop_ev.wait(timeout=2.0)

    thread = threading.Thread(target=_wait, args=(stop,))
    thread.start()
    orch._active[cid] = _CampaignWorker(
        campaign_id=cid,
        thread=thread,
        stop=stop,
        lock=SimpleNamespace(release=lambda: None),
    )
    orch._shutdown_campaigns()
    assert not orch._active
    assert stop.is_set()


def test_reap_if_due_calls_reaper(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    orch = _make_orch(_Campaigns([]), _Runs([]))
    monkeypatch.setattr(orch.reaper, "due", lambda _n: True)
    monkeypatch.setattr(orch.reaper, "reap", lambda _n: calls.append(_n) or 1)
    orch._reap_if_due()
    assert calls


def test_serve_forever_runs_one_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    orch = _make_orch(_Campaigns([]), _Runs([]))
    stop = threading.Event()

    def _tick() -> None:
        orch._last_tick = orch.clock.now()
        stop.set()

    monkeypatch.setattr(orch, "tick", _tick)
    monkeypatch.setattr(
        "roboprobe.runner.orchestrator.serve_health",
        lambda *_a, **_k: SimpleNamespace(stop=lambda: None, port=1),
    )
    orch.serve_forever(stop)
    assert orch._health is None
