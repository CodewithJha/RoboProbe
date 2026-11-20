"""Repository contract suite against the in-memory fake (T-015)."""

from __future__ import annotations

import pytest
from tests.fakes.store import InMemoryUnitOfWork

from roboprobe.core.types import CampaignStatus, RunStatus, Verdict
from roboprobe.store.ids import new_uuid
from roboprobe.store.records import (
    CampaignRecord,
    NewRun,
    SpaceRecord,
    StrategyStateRecord,
    SutProfileRecord,
)

pytestmark = pytest.mark.contract


def test_uow_rollback_discards_writes() -> None:
    shared = InMemoryUnitOfWork()
    with pytest.raises(RuntimeError, match="boom"), shared as uow:
        uow.sut_profiles.add(
            SutProfileRecord(id="p", backend="kinematic2d", config={}, config_hash="h")
        )
        raise RuntimeError("boom")
    with shared as uow:
        assert uow.sut_profiles.get("p") is None


def test_uow_commit_persists() -> None:
    shared = InMemoryUnitOfWork()
    with shared as uow:
        uow.spaces.add(SpaceRecord(id="wh", version="abc", name="n", definition={"k": 1}))
    with shared as uow:
        assert uow.spaces.get("wh", "abc") is not None


def test_insert_batch_idempotent() -> None:
    uow = InMemoryUnitOfWork()
    with uow:
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
                budget=10,
                oracle_config={},
                status=CampaignStatus.CREATED,
            )
        )
        run = NewRun(
            campaign_id=cid,
            ordinal=0,
            backend="kinematic2d",
            scenario_hash="h",
            scenario_values={},
            x_unit=(0.1,),
            seed=1,
            phase="explore",
        )
        first = uow.runs.insert_batch([run])
        second = uow.runs.insert_batch([run.model_copy(update={"id": new_uuid()})])
        page = uow.runs.list_for_campaign(cid, limit=10)
        assert len(page.items) == 1
        assert first[0] != second[0]


def test_history_skips_invalid() -> None:
    uow = InMemoryUnitOfWork()
    with uow:
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
                budget=10,
                oracle_config={},
                status=CampaignStatus.RUNNING,
            )
        )
        ids = uow.runs.insert_batch(
            [
                NewRun(
                    campaign_id=cid,
                    ordinal=i,
                    backend="kinematic2d",
                    scenario_hash="h",
                    scenario_values={},
                    x_unit=(0.2,),
                    seed=i,
                    phase="explore",
                )
                for i in range(2)
            ]
        )
        good = uow.runs.get(ids[0])
        bad = uow.runs.get(ids[1])
        assert good is not None and bad is not None
        uow.runs._db.runs[ids[0]] = good.model_copy(
            update={"status": RunStatus.DONE, "verdict": Verdict.FAIL, "robustness": -0.2}
        )
        uow.runs._db.runs[ids[1]] = bad.model_copy(
            update={"status": RunStatus.DONE, "verdict": Verdict.INVALID, "robustness": None}
        )
        hist = uow.runs.history(cid)
        assert len(hist) == 1
        assert hist[0].run_id == ids[0]


def test_strategy_upsert() -> None:
    uow = InMemoryUnitOfWork()
    cid = new_uuid()
    with uow:
        uow.strategy_states.upsert(StrategyStateRecord(campaign_id=cid, n_obs=1, state={"a": 1}))
        uow.strategy_states.upsert(StrategyStateRecord(campaign_id=cid, n_obs=2, state={"a": 2}))
        got = uow.strategy_states.get(cid)
        assert got is not None
        assert got.n_obs == 2
