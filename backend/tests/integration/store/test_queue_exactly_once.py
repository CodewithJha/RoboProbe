"""SKIP LOCKED exactly-once claim (T-012)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy.orm import sessionmaker
from tests.integration.store._seed import seed_campaign, seed_worker

from roboprobe.store.orm import Base
from roboprobe.store.queue_pg import PostgresRunQueue
from roboprobe.store.uow import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.integration

WORKERS = 4
RUNS = 100
WALL = 300.0
SIM = 120.0


def test_four_claimers_hundred_runs(pg_engine) -> None:
    Base.metadata.drop_all(pg_engine)
    Base.metadata.create_all(pg_engine)
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with SqlAlchemyUnitOfWork(factory, notify_channel="roboprobe_events") as uow:
        _cid, ids = seed_campaign(uow, n_runs=RUNS)
        seed_worker(uow)
    queue = PostgresRunQueue(
        factory,
        notify_channel="roboprobe_events",
        wall_timeout_s=WALL,
        sim_time_budget_s=SIM,
    )
    claimed: list = []

    def worker(slot: int) -> list:
        got = []
        wid = f"host:1:{slot}"
        with SqlAlchemyUnitOfWork(factory, notify_channel="roboprobe_events") as uow:
            seed_worker(uow, wid)
        while True:
            item = queue.claim(wid, "kinematic2d")
            if item is None:
                break
            got.append(item.run_id)
        return got

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for part in pool.map(worker, range(WORKERS)):
            claimed.extend(part)
    assert len(claimed) == RUNS
    assert len(set(claimed)) == RUNS
    assert set(claimed) == set(ids)
    assert queue.depth("kinematic2d") == 0
