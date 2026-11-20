"""Reaper fake-clock timing tests (T-042a)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from tests.fakes.store import InMemoryRunQueue, InMemoryUnitOfWork

from roboprobe.core.clock import FakeClock
from roboprobe.core.settings.runner import RunnerSettings
from roboprobe.core.types import CampaignStatus, RunStatus
from roboprobe.runner.reaper import Reaper, next_reap_due
from roboprobe.store.records import (
    CampaignRecord,
    NewRun,
    SpaceRecord,
    SutProfileRecord,
    WorkerRecord,
)

pytestmark = pytest.mark.unit


def _setup(
    *, heartbeat_timeout_s: float = 30.0, max_attempts: int = 3
) -> tuple[InMemoryUnitOfWork, InMemoryRunQueue, Reaper, FakeClock, object]:
    settings = RunnerSettings(
        heartbeat_timeout_s=heartbeat_timeout_s,
        max_attempts=max_attempts,
        reaper_interval_s=10.0,
    )
    clock = FakeClock(start=datetime(2020, 1, 1, tzinfo=UTC))
    uow = InMemoryUnitOfWork()
    queue = InMemoryRunQueue(uow, wall_timeout_s=60.0, sim_time_budget_s=30.0)
    cid = uuid4()
    wid = "host:1:0"
    with uow:
        uow.sut_profiles.add(
            SutProfileRecord(id="sut", backend="fake", config={}, config_hash="c" * 16)
        )
        uow.spaces.add(SpaceRecord(id="s", version="v", name="n", definition={}))
        uow.campaigns.add(
            CampaignRecord(
                id=cid,
                name="c",
                space_id="s",
                space_version="v",
                sut_profile_id="sut",
                backend="fake",
                strategy_id="S-RANDOM",
                seed=1,
                budget=10,
                oracle_config={},
                status=CampaignStatus.RUNNING,
            )
        )
        uow.workers.register(
            WorkerRecord(
                id=wid,
                backend="fake",
                status="BUSY",
                capabilities={},
                version="0.0.1",
                last_heartbeat=clock.now(),
            )
        )
        uow.runs.insert_batch(
            [
                NewRun(
                    campaign_id=cid,
                    ordinal=0,
                    backend="fake",
                    scenario_hash="a" * 16,
                    scenario_values={},
                    x_unit=(0.1,),
                    seed=1,
                    phase="baseline",
                )
            ]
        )
        uow.commit()
    claimed = queue.claim(wid, "fake")
    assert claimed is not None
    queue.mark_running(claimed.run_id)
    reaper = Reaper(queue=queue, uow_factory=lambda: uow, settings=settings, clock=clock)
    return uow, queue, reaper, clock, claimed.run_id


def test_default_timeout_requeues() -> None:
    uow, _queue, reaper, clock, run_id = _setup()
    assert reaper.reap(clock.now()) == 0
    clock.advance(29.0)
    assert reaper.reap(clock.now()) == 0
    clock.advance(2.0)  # total 31 > 30; worker heartbeat still at t0
    assert reaper.reap(clock.now()) == 1
    with uow:
        run = uow.runs.get(run_id)
        assert run is not None
        assert run.status is RunStatus.PENDING
        worker = uow.workers.get("host:1:0")
        assert worker is not None
        assert worker.status == "OFFLINE"


def test_overridden_timeout_and_schedule() -> None:
    uow, _queue, reaper, clock, run_id = _setup(heartbeat_timeout_s=5.0, max_attempts=2)
    with uow:
        uow.workers.heartbeat("host:1:0", at=clock.now())
        uow.commit()
    clock.advance(6.0)
    with uow:
        uow.workers.heartbeat("host:1:0", at=clock.now() - timedelta(seconds=6))
        uow.commit()
    assert reaper.reap(clock.now()) == 1
    due = next_reap_due(clock.now(), 10.0)
    assert due == clock.now() + timedelta(seconds=10.0)
    with uow:
        assert uow.runs.get(run_id) is not None
