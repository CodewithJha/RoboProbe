"""Scenario space repository."""

# ruff: noqa: D102, D107

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from roboprobe.store.mapping import space_record
from roboprobe.store.orm import ScenarioSpaceRow
from roboprobe.store.pagination import Page, clamp_limit, extra_item
from roboprobe.store.records import SpaceRecord


class SqlSpaceRepo:
    """Implements: SpaceRepo."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, space_id: str, version: str) -> SpaceRecord | None:
        row = self._s.get(ScenarioSpaceRow, (space_id, version))
        return None if row is None else space_record(row)

    def add(self, record: SpaceRecord) -> None:
        self._s.add(
            ScenarioSpaceRow(
                id=record.id,
                version=record.version,
                name=record.name,
                definition=dict(record.definition),
                schema_version=record.schema_version,
            )
        )
        self._s.flush()

    def list(self, *, limit: int | None = None, cursor: str | None = None) -> Page[SpaceRecord]:
        size = clamp_limit(limit)
        stmt = select(ScenarioSpaceRow).order_by(ScenarioSpaceRow.id, ScenarioSpaceRow.version)
        if cursor is not None:
            sid, _, ver = cursor.partition("\t")
            stmt = stmt.where(
                (ScenarioSpaceRow.id > sid)
                | ((ScenarioSpaceRow.id == sid) & (ScenarioSpaceRow.version > ver))
            )
        rows = self._s.scalars(stmt.limit(size + 1)).all()
        items, extra = extra_item([space_record(r) for r in rows], size)
        nxt = None if extra is None else f"{items[-1].id}\t{items[-1].version}"
        return Page(items=items, next_cursor=nxt)
