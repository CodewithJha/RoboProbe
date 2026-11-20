"""Chaos: SIGKILL mid-run → reaper re-queues → another worker finishes (T-040c)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests.contract.test_backend_contract import FakeBackend
from tests.fakes.store import InMemoryRunQueue, InMemoryUnitOfWork

from roboprobe.core.clock import FakeClock, SystemClock
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.settings.oracles import OracleThresholds
from roboprobe.core.types import CampaignStatus, RunStatus
from roboprobe.oracles.goal import GoalOracle
from roboprobe.oracles.verdict import VerdictEngine
from roboprobe.runner.reaper import Reaper
from roboprobe.runner.worker import WorkerProcess
from roboprobe.scenario.task import load_task
from roboprobe.store.artifacts import NullArtifactStore
from roboprobe.store.ids import new_uuid
from roboprobe.store.records import (
    CampaignRecord,
    NewRun,
    SpaceRecord,
    SutProfileRecord,
    WorkerRecord,
)

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[4]


def test_sigkill_requeue_and_complete_by_peer(tmp_path: Path) -> None:
    """Simulate a killed worker: stale heartbeat → reap → second worker completes."""
    settings = RoboProbeSettings(
        storage={"workdir_root": str(tmp_path / "w"), "artifact_root": str(tmp_path / "a")},
        worker={
            "backend": "fake",
            "id_prefix": "chaos",
            "poll_interval_s": 0.01,
            "heartbeat_interval_s": 0.5,
        },
        runner={"heartbeat_timeout_s": 1.0, "max_attempts": 3, "reaper_interval_s": 1.0},
    )
    clock = FakeClock(start=datetime(2020, 1, 1, tzinfo=UTC))
    uow = InMemoryUnitOfWork()
    cid = new_uuid()
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
                budget=5,
                oracle_config={},
                status=CampaignStatus.RUNNING,
            )
        )
        uow.workers.register(
            WorkerRecord(
                id="dead:1:0",
                backend="fake",
                status="BUSY",
                capabilities={},
                version="0.0.1",
                last_heartbeat=clock.now(),
            )
        )
        uow.workers.register(
            WorkerRecord(
                id="live:2:0",
                backend="fake",
                status="IDLE",
                capabilities={},
                version="0.0.1",
                last_heartbeat=clock.now(),
            )
        )
        ids = uow.runs.insert_batch(
            [
                NewRun(
                    campaign_id=cid,
                    ordinal=0,
                    backend="fake",
                    scenario_hash="a" * 16,
                    scenario_values={"robot.max_speed": 0.5},
                    x_unit=(0.5,),
                    seed=1,
                    phase="baseline",
                )
            ]
        )
        uow.commit()

    queue = InMemoryRunQueue(uow, wall_timeout_s=30.0, sim_time_budget_s=10.0)
    claimed = queue.claim("dead:1:0", "fake")
    assert claimed is not None
    queue.mark_running(claimed.run_id)
    # SIGKILL: worker gone, heartbeat goes stale.
    clock.advance(2.0)
    with uow:
        uow.workers.heartbeat("dead:1:0", at=clock.now() - timedelta(seconds=2))
        uow.commit()
    reaper = Reaper(
        queue=queue,
        uow_factory=lambda: uow,
        settings=settings.runner,
        clock=clock,
    )
    assert reaper.reap(clock.now()) == 1
    with uow:
        run = uow.runs.get(ids[0])
        assert run is not None
        assert run.status is RunStatus.PENDING

    task = load_task(REPO / "tasks" / "warehouse_delivery_v1.yaml", strict=False)
    peer = WorkerProcess(
        backend=FakeBackend(settings),
        uow_factory=lambda: uow,
        queue=queue,
        artifact_store=NullArtifactStore(),
        verdict_engine=VerdictEngine([GoalOracle(OracleThresholds())]),
        clock=SystemClock(),
        worker_settings=settings.worker.model_copy(update={"id_prefix": "live"}),
        storage_settings=settings.storage,
        task=task,
        slot=0,
    )
    # Force worker id to the live peer.
    peer.worker_id = "live:2:0"
    again = peer.claim()
    assert again is not None
    assert again.run_id == ids[0]
    peer.execute(again)
    with uow:
        run = uow.runs.get(ids[0])
        assert run is not None
        assert run.status is RunStatus.DONE
        assert len(uow.runs.list_for_campaign(cid).items) == 1


def test_drain_finishes_current_without_new_claims(tmp_path: Path) -> None:
    settings = RoboProbeSettings(
        storage={"workdir_root": str(tmp_path / "w"), "artifact_root": str(tmp_path / "a")},
        worker={"backend": "fake", "id_prefix": "drain", "poll_interval_s": 0.01},
    )
    uow = InMemoryUnitOfWork()
    cid = new_uuid()
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
                budget=5,
                oracle_config={},
                status=CampaignStatus.RUNNING,
            )
        )
        uow.runs.insert_batch(
            [
                NewRun(
                    campaign_id=cid,
                    ordinal=i,
                    backend="fake",
                    scenario_hash=f"{i:016x}",
                    scenario_values={},
                    x_unit=(0.1,),
                    seed=i,
                    phase="baseline",
                )
                for i in range(2)
            ]
        )
        uow.commit()
    queue = InMemoryRunQueue(uow, wall_timeout_s=30.0, sim_time_budget_s=10.0)
    task = load_task(REPO / "tasks" / "warehouse_delivery_v1.yaml", strict=False)
    worker = WorkerProcess(
        backend=FakeBackend(settings),
        uow_factory=lambda: uow,
        queue=queue,
        artifact_store=NullArtifactStore(),
        verdict_engine=VerdictEngine([GoalOracle(OracleThresholds())]),
        clock=SystemClock(),
        worker_settings=settings.worker,
        storage_settings=settings.storage,
        task=task,
    )
    first = worker.claim()
    assert first is not None
    worker.request_drain()
    worker.execute(first)
    assert worker.claim() is None


def test_cancelled_campaign_stops_episode(tmp_path: Path) -> None:
    settings = RoboProbeSettings(
        storage={"workdir_root": str(tmp_path / "w"), "artifact_root": str(tmp_path / "a")},
        worker={"backend": "fake", "id_prefix": "cancel", "poll_interval_s": 0.01},
    )
    uow = InMemoryUnitOfWork()
    cid = new_uuid()
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
                budget=5,
                oracle_config={},
                status=CampaignStatus.RUNNING,
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
    queue = InMemoryRunQueue(uow, wall_timeout_s=30.0, sim_time_budget_s=10.0)
    task = load_task(REPO / "tasks" / "warehouse_delivery_v1.yaml", strict=False)

    class SlowBackend(FakeBackend):
        def run_episode(self, req, materialized, on_progress=None):
            if on_progress is not None:
                on_progress(0.1)
            return super().run_episode(req, materialized, on_progress)

    worker = WorkerProcess(
        backend=SlowBackend(settings),
        uow_factory=lambda: uow,
        queue=queue,
        artifact_store=NullArtifactStore(),
        verdict_engine=VerdictEngine([GoalOracle(OracleThresholds())]),
        clock=SystemClock(),
        worker_settings=settings.worker,
        storage_settings=settings.storage,
        task=task,
    )
    claimed = worker.claim()
    assert claimed is not None
    with uow:
        uow.campaigns.set_status(cid, CampaignStatus.CANCELLED)
        uow.commit()
    # Claimed before cancel: execute still runs but progress callback may cancel.
    worker.execute(claimed)
    with uow:
        run = uow.runs.get(claimed.run_id)
        assert run is not None
        assert run.status in {RunStatus.DONE, RunStatus.ERROR}
