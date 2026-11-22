"""Unit tests for :mod:`roboprobe.runner.analysis_jobs` (T-075b)."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from tests.fakes.store import InMemoryUnitOfWork

from roboprobe.analysis.base import AnalysisKind, AnalysisReport
from roboprobe.core.clock import FakeClock
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import CampaignStatus
from roboprobe.runner.analysis_jobs import AnalysisJobRunner
from roboprobe.runner.lifecycle import CampaignService
from roboprobe.store.records import CampaignRecord, SpaceRecord, SutProfileRecord

pytestmark = pytest.mark.unit


class _InlineExecutor:
    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[UUID]:
        fut: Future[UUID] = Future()
        try:
            fut.set_result(fn(*args, **kwargs))
        except Exception as exc:
            fut.set_exception(exc)
        return fut


def _settings() -> RoboProbeSettings:
    return RoboProbeSettings()


def _runner(
    uow: InMemoryUnitOfWork,
    *,
    analyze_fn: Any | None = None,
    executor: Any | None = None,
) -> AnalysisJobRunner:
    clock = FakeClock(datetime(2025, 6, 1, tzinfo=UTC))
    services = CampaignService(lambda: uow)
    return AnalysisJobRunner(
        lambda: uow,
        object(),
        _settings(),
        executor if executor is not None else _InlineExecutor(),
        clock,
        campaigns=services,
        analyze_fn=analyze_fn,
        load_space=lambda _sid, _ver: None,  # type: ignore[arg-type, return-value]
    )


def _seed(uow: InMemoryUnitOfWork, *, status: CampaignStatus) -> UUID:
    cid = uuid4()
    with uow:
        uow.sut_profiles.add(
            SutProfileRecord(id="sut", backend="kinematic2d", config={}, config_hash="a" * 16)
        )
        uow.spaces.add(SpaceRecord(id="warehouse_v1", version="v1", name="w", definition={}))
        uow.campaigns.add(
            CampaignRecord(
                id=cid,
                name="c",
                space_id="warehouse_v1",
                space_version="v1",
                sut_profile_id="sut",
                backend="kinematic2d",
                strategy_id="S-RANDOM",
                seed=1,
                budget=100,
                oracle_config={},
                status=status,
            )
        )
        uow.commit()
    return cid


def test_incremental_triggers_at_25_and_50() -> None:
    uow = InMemoryUnitOfWork()
    calls: list[tuple[UUID, AnalysisKind]] = []

    def _analyze(
        campaign_id: UUID,
        _uow: object,
        _store: object,
        *,
        kind: AnalysisKind,
        **_kwargs: object,
    ) -> AnalysisReport:
        calls.append((campaign_id, kind))
        return AnalysisReport(
            analysis_id=uuid4(),
            campaign_id=campaign_id,
            kind=kind,
            status="OK",
            analysis_schema_version=1,
            n_runs=0,
            n_fail=0,
            mode_codes=[],
            warnings=[],
            summary={},
            duration_s=0.0,
        )

    runner = _runner(uow, analyze_fn=_analyze)
    cid = _seed(uow, status=CampaignStatus.RUNNING)

    for n in (1, 24, 26, 49, 51):
        runner.on_run_finished(cid, n)
        assert calls == []

    runner.on_run_finished(cid, 25)
    assert calls == [(cid, AnalysisKind.INCREMENTAL)]

    runner.on_run_finished(cid, 50)
    assert calls == [(cid, AnalysisKind.INCREMENTAL), (cid, AnalysisKind.INCREMENTAL)]


def test_concurrent_analysis_skips_second_job() -> None:
    uow = InMemoryUnitOfWork()
    entered = threading.Event()

    def _slow_analyze(
        campaign_id: UUID,
        _uow: object,
        _store: object,
        *,
        kind: AnalysisKind,
        **_kwargs: object,
    ) -> AnalysisReport:
        entered.set()
        time.sleep(2.0)
        return AnalysisReport(
            analysis_id=uuid4(),
            campaign_id=campaign_id,
            kind=kind,
            status="OK",
            analysis_schema_version=1,
            n_runs=0,
            n_fail=0,
            mode_codes=[],
            warnings=[],
            summary={},
            duration_s=0.0,
        )

    pool = ThreadPoolExecutor(max_workers=2)
    runner = _runner(uow, analyze_fn=_slow_analyze, executor=pool)
    cid = _seed(uow, status=CampaignStatus.RUNNING)
    try:
        first = runner.schedule(cid, AnalysisKind.INCREMENTAL)
        assert first is not None
        assert entered.wait(timeout=5.0)
        second = runner.schedule(cid, AnalysisKind.INCREMENTAL)
        assert second is None
        assert first.result(timeout=10.0)
    finally:
        pool.shutdown(wait=True)


def test_analyzing_failure_still_completes_campaign() -> None:
    uow = InMemoryUnitOfWork()
    cid = _seed(uow, status=CampaignStatus.ANALYZING)

    def _fail(
        campaign_id: UUID,
        _uow: object,
        _store: object,
        *,
        kind: AnalysisKind,
        **_kwargs: object,
    ) -> AnalysisReport:
        return AnalysisReport(
            analysis_id=uuid4(),
            campaign_id=campaign_id,
            kind=kind,
            status="ERROR",
            analysis_schema_version=1,
            n_runs=0,
            n_fail=0,
            mode_codes=[],
            warnings=["clustering: boom"],
            summary={},
            duration_s=0.0,
        )

    runner = _runner(uow, analyze_fn=_fail)
    with uow:
        campaign = uow.campaigns.get(cid)
        assert campaign is not None
    runner.on_campaign_status(campaign)
    with uow:
        updated = uow.campaigns.get(cid)
        assert updated is not None
        assert updated.status is CampaignStatus.COMPLETED
        assert updated.status_reason == "analysis ERROR"


def test_enqueue_returns_reserved_id_without_waiting_and_reuses_pending() -> None:
    uow = InMemoryUnitOfWork()
    cid = _seed(uow, status=CampaignStatus.RUNNING)
    started = threading.Event()
    release = threading.Event()

    def analyze(campaign_id: UUID, _uow: object, _store: object, **kwargs: Any) -> AnalysisReport:
        started.set()
        release.wait(timeout=5)
        return AnalysisReport(
            analysis_id=kwargs["analysis_id"],
            campaign_id=campaign_id,
            kind=AnalysisKind.FULL,
            status="OK",
            analysis_schema_version=1,
            n_runs=0,
            n_fail=0,
            mode_codes=[],
            warnings=[],
            summary={},
            duration_s=0,
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        runner = _runner(uow, analyze_fn=analyze, executor=pool)
        try:
            reserved = runner.enqueue(cid, AnalysisKind.FULL)
            assert started.wait(timeout=2)
            assert runner.enqueue(cid, AnalysisKind.FULL) == reserved
        finally:
            release.set()
