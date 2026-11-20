"""Shared seed helpers for store integration tests."""

from __future__ import annotations

from roboprobe.core.types import CampaignStatus
from roboprobe.store.ids import new_uuid
from roboprobe.store.ports import UnitOfWork
from roboprobe.store.records import (
    CampaignRecord,
    NewRun,
    SpaceRecord,
    SutProfileRecord,
    WorkerRecord,
)


def seed_campaign(
    uow: UnitOfWork, *, status: CampaignStatus = CampaignStatus.RUNNING, n_runs: int = 0
):
    uow.sut_profiles.add(
        SutProfileRecord(id="p", backend="kinematic2d", config={}, config_hash="h")
    )
    uow.spaces.add(SpaceRecord(id="s", version="v", name="n", definition={}))
    cid = new_uuid()
    uow.campaigns.add(
        CampaignRecord(
            id=cid,
            name="c",
            space_id="s",
            space_version="v",
            sut_profile_id="p",
            backend="kinematic2d",
            strategy_id="S-RANDOM",
            seed=1,
            budget=100,
            oracle_config={},
            status=status,
        )
    )
    ids = ()
    if n_runs:
        ids = uow.runs.insert_batch(
            [
                NewRun(
                    campaign_id=cid,
                    ordinal=i,
                    backend="kinematic2d",
                    scenario_hash=f"h{i}",
                    scenario_values={"i": i},
                    x_unit=(0.1,),
                    seed=i,
                    phase="explore",
                    priority=10 if i == 0 else 100,
                )
                for i in range(n_runs)
            ]
        )
    return cid, ids


def seed_worker(uow: UnitOfWork, worker_id: str = "host:1:0") -> None:
    uow.workers.register(
        WorkerRecord(
            id=worker_id,
            backend="kinematic2d",
            status="IDLE",
            capabilities={},
            version="0.0.1",
        )
    )
