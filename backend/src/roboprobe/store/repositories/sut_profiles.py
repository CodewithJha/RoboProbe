"""SUT profile repository."""

# ruff: noqa: D102, D107

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from roboprobe.store.mapping import sut_record
from roboprobe.store.orm import SutProfileRow
from roboprobe.store.pagination import Page, clamp_limit, extra_item
from roboprobe.store.records import SutProfileRecord


class SqlSutProfileRepo:
    """Implements: SutProfileRepo."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, profile_id: str) -> SutProfileRecord | None:
        row = self._s.get(SutProfileRow, profile_id)
        return None if row is None else sut_record(row)

    def add(self, record: SutProfileRecord) -> None:
        self._s.add(
            SutProfileRow(
                id=record.id,
                backend=record.backend,
                config=dict(record.config),
                config_hash=record.config_hash,
            )
        )

    def list(
        self, *, limit: int | None = None, cursor: str | None = None
    ) -> Page[SutProfileRecord]:
        size = clamp_limit(limit)
        stmt = select(SutProfileRow).order_by(SutProfileRow.id)
        if cursor is not None:
            stmt = stmt.where(SutProfileRow.id > cursor)
        rows = self._s.scalars(stmt.limit(size + 1)).all()
        items, extra = extra_item([sut_record(r) for r in rows], size)
        nxt = None if extra is None else items[-1].id
        return Page(items=items, next_cursor=nxt)
