"""PostgreSQL scheduling snapshots used by campaign replenishment (T-130)."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.orm import Session
from tests.integration.store._seed import seed_campaign

from roboprobe.core.types import RunStatus
from roboprobe.store.orm import RunRow
from roboprobe.store.uow import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.integration

_INFLIGHT = frozenset(
    {RunStatus.PENDING, RunStatus.CLAIMED, RunStatus.RUNNING, RunStatus.EVALUATING}
)


def test_scheduling_snapshot_counts_and_orders_runs(store_session: Session) -> None:
    uow = SqlAlchemyUnitOfWork(lambda: store_session, notify_channel="roboprobe_events")
    uow.bind_session(store_session)
    cid, _ = seed_campaign(uow)
    other, _ = seed_campaign(uow)

    empty = uow.runs.scheduling_snapshot(cid, inflight_statuses=_INFLIGHT, count_invalid=False)
    assert (empty.budget_used, empty.next_ordinal, empty.inflight_vectors) == (0, 0, ())

    store_session.add_all(
        RunRow(
            id=UUID(int=run_id),
            campaign_id=campaign_id,
            ordinal=ordinal,
            backend="kinematic2d",
            scenario_hash=f"h{ordinal}",
            scenario_values={},
            x_unit=[run_id / 10],
            seed=ordinal,
            phase="explore",
            status=status.value,
            verdict=verdict,
        )
        for run_id, campaign_id, ordinal, status, verdict in (
            (4, cid, 0, RunStatus.PENDING, None),
            (1, cid, 1, RunStatus.CLAIMED, None),
            (3, cid, 2, RunStatus.RUNNING, None),
            (2, cid, 3, RunStatus.EVALUATING, None),
            (5, cid, 4, RunStatus.DONE, "PASS"),
            (6, cid, 5, RunStatus.DONE, None),
            (7, cid, 6, RunStatus.DONE, "INVALID"),
            (8, cid, 7, RunStatus.ERROR, "INVALID"),
            (9, cid, 50, RunStatus.CANCELLED, None),
            (10, other, 100, RunStatus.PENDING, None),
        )
    )
    store_session.flush()

    valid_only = uow.runs.scheduling_snapshot(cid, inflight_statuses=_INFLIGHT, count_invalid=False)
    assert valid_only.budget_used == 6
    assert valid_only.next_ordinal == 51
    assert valid_only.inflight_vectors == ((0.1,), (0.2,), (0.3,), (0.4,))
    with_invalid = uow.runs.scheduling_snapshot(
        cid, inflight_statuses=_INFLIGHT, count_invalid=True
    )
    assert with_invalid.budget_used == 8
    assert with_invalid.next_ordinal == valid_only.next_ordinal
    assert with_invalid.inflight_vectors == valid_only.inflight_vectors
