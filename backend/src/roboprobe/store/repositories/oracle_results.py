"""Oracle result repository."""

# ruff: noqa: D102, D107

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from roboprobe.store.mapping import oracle_record
from roboprobe.store.orm import OracleResultRow
from roboprobe.store.records import OracleResultRecord


class SqlOracleResultRepo:
    """Implements: OracleResultRepo."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def replace_for_run(self, run_id: UUID, results: Sequence[OracleResultRecord]) -> None:
        self._s.execute(delete(OracleResultRow).where(OracleResultRow.run_id == run_id))
        for item in results:
            self._s.add(
                OracleResultRow(
                    run_id=run_id,
                    oracle_id=item.oracle_id,
                    failure_class=str(item.failure_class),
                    severity=item.severity,
                    violated=item.violated,
                    robustness=item.robustness,
                    first_violation_t=item.first_violation_t,
                    details=dict(item.details),
                )
            )

    def list_for_run(self, run_id: UUID) -> tuple[OracleResultRecord, ...]:
        rows = self._s.scalars(
            select(OracleResultRow)
            .where(OracleResultRow.run_id == run_id)
            .order_by(OracleResultRow.oracle_id)
        ).all()
        return tuple(oracle_record(r) for r in rows)
