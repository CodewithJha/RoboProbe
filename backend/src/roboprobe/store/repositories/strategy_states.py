"""Strategy checkpoint repository."""

# ruff: noqa: D102, D107

from __future__ import annotations

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from roboprobe.store.flush import execute
from roboprobe.store.mapping import strategy_record
from roboprobe.store.orm import StrategyStateRow
from roboprobe.store.records import StrategyStateRecord


class SqlStrategyStateRepo:
    """Implements: StrategyStateRepo."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, campaign_id: UUID) -> StrategyStateRecord | None:
        row = self._s.get(StrategyStateRow, campaign_id)
        return None if row is None else strategy_record(row)

    def upsert(self, record: StrategyStateRecord) -> None:
        stmt = insert(StrategyStateRow).values(
            campaign_id=record.campaign_id,
            n_obs=record.n_obs,
            state=dict(record.state),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["campaign_id"],
            set_={"n_obs": stmt.excluded.n_obs, "state": stmt.excluded.state},
        )
        execute(self._s, stmt)
