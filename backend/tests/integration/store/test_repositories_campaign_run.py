"""Campaign/run repository integration tests (T-011a)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session
from tests.integration.store._seed import seed_campaign

from roboprobe.core.types import CampaignStatus, FailureClass, Verdict
from roboprobe.store.orm import RunRow
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


def test_history_projects_ordered_observations(store_session: Session) -> None:
    uow = SqlAlchemyUnitOfWork(lambda: store_session, notify_channel="roboprobe_events")
    uow.bind_session(store_session)
    cid, _ = seed_campaign(uow)
    rows = [
        RunRow(
            campaign_id=cid,
            ordinal=ordinal,
            repeat_index=repeat,
            backend="kinematic2d",
            scenario_hash=f"h{ordinal}",
            scenario_values={},
            x_unit=[0.25],
            seed=ordinal,
            phase=phase,
            status=status,
            verdict=verdict,
            primary_failure=failure,
            robustness=-0.25,
            manifest={"evidence": "stored independently of the observation"},
        )
        for ordinal, repeat, phase, status, verdict, failure in (
            (4, 0, "manual", "DONE", "PASS", None),
            (0, 1, "explore", "DONE", "FAIL", "F-COL"),
            (1, 0, "confirm", "DONE", "FAIL", "F-COL"),
            (0, 0, "replay", "DONE", "FAIL", "unknown"),
            (2, 0, "explore", "DONE", "INVALID", None),
            (3, 0, "explore", "RUNNING", None, None),
        )
    ]
    store_session.add_all(rows)
    store_session.flush()
    ids = [row.id for row in rows]
    store_session.expunge_all()
    loaded_runs: list[RunRow] = []

    def record_loaded_run(_session: Session, instance: object) -> None:
        if isinstance(instance, RunRow):
            loaded_runs.append(instance)

    event.listen(store_session, "loaded_as_persistent", record_loaded_run)
    history = uow.runs.history(cid)
    assert [item.run_id for item in history] == [ids[3], ids[1]]
    assert history[0].failure_class is None
    assert history[1].failure_class is FailureClass.COL
    assert history[1].x_unit == (0.25,)
    assert history[1].robustness == -0.25
    assert history[1].verdict is Verdict.FAIL
    assert [item.run_id for item in uow.runs.history(cid, exclude_phases=frozenset())] == [
        ids[3],
        ids[1],
        ids[2],
        ids[0],
    ]
    assert [
        item.run_id for item in uow.runs.history(cid, exclude_phases=frozenset({"replay"}))
    ] == [ids[1], ids[2], ids[0]]
    assert loaded_runs == []
