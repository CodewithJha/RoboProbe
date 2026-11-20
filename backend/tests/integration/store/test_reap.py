"""Reaper SQL (T-012)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker
from tests.integration.store._seed import seed_campaign, seed_worker

from roboprobe.core.types import RunStatus, Verdict
from roboprobe.store.orm import Base
from roboprobe.store.queue_pg import PostgresRunQueue
from roboprobe.store.uow import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.integration


def test_reap_stale_worker(pg_engine) -> None:
    Base.metadata.drop_all(pg_engine)
    Base.metadata.create_all(pg_engine)
    factory = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)
    queue = PostgresRunQueue(
        factory, notify_channel="roboprobe_events", wall_timeout_s=300.0, sim_time_budget_s=120.0
    )
    with SqlAlchemyUnitOfWork(factory, notify_channel="roboprobe_events") as uow:
        _cid, ids = seed_campaign(uow, n_runs=1)
        seed_worker(uow, "host:1:0")
    claimed = queue.claim("host:1:0", "kinematic2d")
    assert claimed is not None
    now = datetime.now(UTC)
    with SqlAlchemyUnitOfWork(factory, notify_channel="roboprobe_events") as uow:
        uow.workers.heartbeat("host:1:0", at=now - timedelta(seconds=120))
    n = queue.reap(now, heartbeat_timeout_s=30.0, max_attempts=3)
    assert n == 1
    with SqlAlchemyUnitOfWork(factory, notify_channel="roboprobe_events") as uow:
        run = uow.runs.get(ids[0])
        assert run is not None
        assert run.status is RunStatus.PENDING
        assert run.worker_id is None


def test_reap_exhausts_attempts(pg_engine) -> None:
    Base.metadata.drop_all(pg_engine)
    Base.metadata.create_all(pg_engine)
    factory = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)
    queue = PostgresRunQueue(
        factory, notify_channel="roboprobe_events", wall_timeout_s=300.0, sim_time_budget_s=120.0
    )
    with SqlAlchemyUnitOfWork(factory, notify_channel="roboprobe_events") as uow:
        _cid, ids = seed_campaign(uow, n_runs=1)
        seed_worker(uow, "host:1:0")
    claimed = queue.claim("host:1:0", "kinematic2d")
    assert claimed is not None
    now = datetime.now(UTC)
    with SqlAlchemyUnitOfWork(factory, notify_channel="roboprobe_events") as uow:
        uow.workers.heartbeat("host:1:0", at=now - timedelta(seconds=120))
    n = queue.reap(now, heartbeat_timeout_s=30.0, max_attempts=1)
    assert n == 1
    with SqlAlchemyUnitOfWork(factory, notify_channel="roboprobe_events") as uow:
        run = uow.runs.get(ids[0])
        assert run is not None
        assert run.status is RunStatus.ERROR
        assert run.verdict is Verdict.INVALID
