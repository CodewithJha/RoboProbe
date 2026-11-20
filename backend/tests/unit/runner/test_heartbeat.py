"""Worker heartbeat thread with fake clock (T-040b)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from tests.contract.test_backend_contract import FakeBackend
from tests.fakes.store import InMemoryRunQueue, InMemoryUnitOfWork

from roboprobe.core.clock import FakeClock
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.settings.oracles import OracleThresholds
from roboprobe.core.types import CampaignStatus
from roboprobe.oracles.goal import GoalOracle
from roboprobe.oracles.verdict import VerdictEngine
from roboprobe.runner.heartbeat import HeartbeatService
from roboprobe.runner.worker import WORKER_BUSY, WorkerProcess
from roboprobe.scenario.task import load_task
from roboprobe.store.artifacts import NullArtifactStore
from roboprobe.store.records import (
    CampaignRecord,
    NewRun,
    SpaceRecord,
    SutProfileRecord,
    WorkerRecord,
)

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[4]


def test_heartbeat_interval_and_busy_status(tmp_path: Path) -> None:
    settings = RoboProbeSettings(
        storage={"workdir_root": str(tmp_path / "w"), "artifact_root": str(tmp_path / "a")},
        worker={
            "backend": "fake",
            "id_prefix": "hb",
            "heartbeat_interval_s": 2.0,
            "health_port": 19101,
        },
    )
    clock = FakeClock(start=datetime(2020, 1, 1, tzinfo=UTC))
    uow = InMemoryUnitOfWork()
    with uow:
        uow.sut_profiles.add(
            SutProfileRecord(id="sut", backend="fake", config={}, config_hash="c" * 16)
        )
        uow.spaces.add(SpaceRecord(id="s", version="v", name="n", definition={}))
        cid = uuid4()
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
    worker = WorkerProcess(
        backend=FakeBackend(settings),
        uow_factory=lambda: uow,
        queue=queue,
        artifact_store=NullArtifactStore(),
        verdict_engine=VerdictEngine([GoalOracle(OracleThresholds())]),
        clock=clock,
        worker_settings=settings.worker,
        storage_settings=settings.storage,
        task=task,
    )
    hb = HeartbeatService(
        worker=worker,
        uow_factory=lambda: uow,
        clock=clock,
        settings=settings.worker,
        retry=settings.runner.retry,
        heartbeat_timeout_s=settings.runner.heartbeat_timeout_s,
        record_factory=lambda wid, backend, version, caps: WorkerRecord(
            id=wid, backend=backend, status="IDLE", capabilities=caps, version=version
        ),
    )
    hb.register()
    with uow:
        row = uow.workers.get(worker.worker_id)
        assert row is not None
        assert row.last_heartbeat == clock.now()

    claimed = worker.claim()
    assert claimed is not None
    worker.current_run_id = claimed.run_id
    hb._beat_once()
    with uow:
        row = uow.workers.get(worker.worker_id)
        assert row is not None
        assert row.status == WORKER_BUSY
        assert row.current_run_id == claimed.run_id

    # Overridden interval is honoured by the service configuration.
    assert hb._settings.heartbeat_interval_s == 2.0
    clock.advance(2.0)
    hb._beat_once()
    with uow:
        row = uow.workers.get(worker.worker_id)
        assert row is not None
        assert row.last_heartbeat == clock.now()
