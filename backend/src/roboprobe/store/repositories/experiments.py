"""Experiment repository."""

# ruff: noqa: D102, D107

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from roboprobe.core.errors import NotFoundError
from roboprobe.store.flush import execute
from roboprobe.store.mapping import experiment_record
from roboprobe.store.orm import ExperimentRow
from roboprobe.store.pagination import Page, clamp_limit, extra_item
from roboprobe.store.records import ExperimentRecord


class SqlExperimentRepo:
    """Implements: ExperimentRepo."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, experiment_id: UUID) -> ExperimentRecord | None:
        row = self._s.get(ExperimentRow, experiment_id)
        return None if row is None else experiment_record(row)

    def add(self, record: ExperimentRecord) -> None:
        self._s.add(
            ExperimentRow(
                id=record.id,
                name=record.name,
                design=dict(record.design),
                status=record.status,
                results=None if record.results is None else dict(record.results),
            )
        )
        self._s.flush()

    def set_status(self, experiment_id: UUID, status: str) -> None:
        result = execute(
            self._s,
            update(ExperimentRow).where(ExperimentRow.id == experiment_id).values(status=status),
        )
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            msg = "experiment not found"
            raise NotFoundError(msg, context={"experiment_id": str(experiment_id)})

    def list(
        self, *, limit: int | None = None, cursor: str | None = None
    ) -> Page[ExperimentRecord]:
        size = clamp_limit(limit)
        stmt = select(ExperimentRow).order_by(ExperimentRow.id)
        if cursor is not None:
            stmt = stmt.where(ExperimentRow.id > UUID(cursor))
        rows = self._s.scalars(stmt.limit(size + 1)).all()
        items, extra = extra_item([experiment_record(r) for r in rows], size)
        nxt = None if extra is None else str(items[-1].id)
        return Page(items=items, next_cursor=nxt)
