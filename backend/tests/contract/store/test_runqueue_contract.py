"""RunQueue contract suite against the in-memory fake (T-015)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tests.fakes.store import InMemoryRunQueue, InMemoryUnitOfWork

from roboprobe.core.errors import ConflictError
from roboprobe.core.types import CampaignStatus, RunStatus, Verdict
from roboprobe.store.ids import new_uuid
from roboprobe.store.records import (
    CampaignRecord,
    NewRun,
    SpaceRecord,
    SutProfileRecord,
    WorkerRecord,
)

pytestmark = pytest.mark.contract

WALL = 300.0
SIM = 120.0


def _seed(uow: InMemoryUnitOfWork, *, n: int = 3, backend: str = "kinematic2d") -> tuple:
    with uow:
        uow.sut_profiles.add(SutProfileRecord(id="p", backend=backend, config={}, config_hash="h"))
        uow.spaces.add(SpaceRecord(id="s", version="v", name="n", definition={}))
        cid = new_uuid()
        uow.campaigns.add(
            CampaignRecord(
                id=cid,
                name="c",
                space_id="s",
                space_version="v",
                sut_profile_id="p",
                backend=backend,
                strategy_id="S-RANDOM",
                seed=1,
                budget=100,
                oracle_config={},
                status=CampaignStatus.RUNNING,
            )
        )
        runs = [
            NewRun(
                campaign_id=cid,
                ordinal=i,
                backend=backend,
                scenario_hash=f"h{i}",
                scenario_values={},
                x_unit=(0.1,),
                seed=i,
                phase="explore",
                priority=10 if i == 0 else 100,
            )
            for i in range(n)
        ]
        ids = uow.runs.insert_batch(runs)
        uow.workers.register(
            WorkerRecord(
                id="w:1:0",
                backend=backend,
                status="IDLE",
                capabilities={},
                version="0",
                last_heartbeat=datetime.now(UTC),
            )
        )
    return uow, cid, ids


def test_claim_priority_and_exactly_once() -> None:
    uow, _cid, ids = _seed(InMemoryUnitOfWork())
    queue = InMemoryRunQueue(uow, wall_timeout_s=WALL, sim_time_budget_s=SIM)
    first = queue.claim("w:1:0", "kinematic2d")
    second = queue.claim("w:1:0", "kinematic2d")
    assert first is not None and second is not None
    assert first.run_id == ids[0]
    assert first.run_id != second.run_id
    claimed = {first.run_id, second.run_id}
    third = queue.claim("w:1:0", "kinematic2d")
    assert third is not None
    claimed.add(third.run_id)
    assert claimed == set(ids)
    assert queue.claim("w:1:0", "kinematic2d") is None


def test_illegal_transition() -> None:
    uow, _cid, ids = _seed(InMemoryUnitOfWork(), n=1)
    queue = InMemoryRunQueue(uow, wall_timeout_s=WALL, sim_time_budget_s=SIM)
    with pytest.raises(ConflictError):
        queue.mark_running(ids[0])


def test_reaper_returns_pending_then_invalid() -> None:
    uow, _cid, _ids = _seed(InMemoryUnitOfWork(), n=1)
    queue = InMemoryRunQueue(uow, wall_timeout_s=WALL, sim_time_budget_s=SIM)
    claimed = queue.claim("w:1:0", "kinematic2d")
    assert claimed is not None
    now = datetime.now(UTC)
    with uow as inner:
        inner.workers.heartbeat("w:1:0", at=now - timedelta(seconds=100))
    n = queue.reap(now, heartbeat_timeout_s=30.0, max_attempts=3)
    assert n == 1
    with uow as inner:
        run = inner.runs.get(claimed.run_id)
        assert run is not None
        assert run.status is RunStatus.PENDING
    claimed2 = queue.claim("w:1:0", "kinematic2d")
    assert claimed2 is not None
    with uow as inner:
        inner.workers.heartbeat("w:1:0", at=now - timedelta(seconds=100))
        run = inner.runs.get(claimed2.run_id)
        assert run is not None
        inner.runs._db.runs[run.id] = run.model_copy(update={"attempt": 3})
        inner.commit()
    n = queue.reap(now, heartbeat_timeout_s=30.0, max_attempts=3)
    assert n == 1
    with uow as inner:
        run = inner.runs.get(claimed2.run_id)
        assert run is not None
        assert run.status is RunStatus.ERROR
        assert run.verdict is Verdict.INVALID
