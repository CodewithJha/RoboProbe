"""Campaign/run repository integration tests (T-011a)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from tests.integration.store._seed import seed_campaign

from roboprobe.core.types import CampaignStatus
from roboprobe.store.records import NewRun, OracleResultRecord, StrategyStateRecord
from roboprobe.store.uow import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.integration


def test_campaign_and_run_roundtrip(uow_factory: Callable[[], SqlAlchemyUnitOfWork]) -> None:
    with uow_factory() as uow:
        cid, ids = seed_campaign(uow, n_runs=2)
        got = uow.campaigns.get(cid)
        assert got is not None
        assert got.status is CampaignStatus.RUNNING
        page = uow.runs.list_for_campaign(cid, limit=1)
        assert len(page.items) == 1
        assert page.next_cursor is not None
        page2 = uow.runs.list_for_campaign(cid, limit=1, cursor=page.next_cursor)
        assert len(page2.items) == 1
        assert {page.items[0].id, page2.items[0].id} == set(ids)
        extra = NewRun(
            campaign_id=cid,
            ordinal=0,
            backend="kinematic2d",
            scenario_hash="h0",
            scenario_values={},
            x_unit=(0.1,),
            seed=0,
            phase="explore",
        )
        uow.runs.insert_batch([extra])
        assert len(uow.runs.list_for_campaign(cid, limit=10).items) == 2
        uow.oracle_results.replace_for_run(
            ids[0],
            [
                OracleResultRecord(
                    run_id=ids[0],
                    oracle_id="O-CLEAR",
                    failure_class="F-COL",
                    severity="failure",
                    violated=True,
                    robustness=-0.5,
                )
            ],
        )
        assert len(uow.oracle_results.list_for_run(ids[0])) == 1
        uow.strategy_states.upsert(StrategyStateRecord(campaign_id=cid, n_obs=0, state={"k": 1}))
        assert uow.strategy_states.get(cid) is not None


def test_uow_rollback(uow_factory: Callable[[], SqlAlchemyUnitOfWork]) -> None:
    cid_holder: dict[str, object] = {}
    with pytest.raises(RuntimeError, match="nope"), uow_factory() as uow:
        cid, _ = seed_campaign(uow, n_runs=0)
        cid_holder["id"] = cid
        raise RuntimeError("nope")
    with uow_factory() as uow:
        # Nested transaction rollback on the test connection: the outer pytest
        # transaction still isolates tests; the UoW rollback drops the save.
        assert uow.campaigns.get(cid_holder["id"]) is None  # type: ignore[arg-type]
