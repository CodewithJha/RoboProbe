"""Transactional outbox repository (docs/11 §4)."""

# ruff: noqa: D102, D107

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from roboprobe.core.types import JsonValue
from roboprobe.store.flush import execute
from roboprobe.store.mapping import event_record
from roboprobe.store.orm import EventRow
from roboprobe.store.pagination import clamp_limit
from roboprobe.store.records import EventRecord


class SqlEventRepo:
    """Implements: EventRepo. ``pg_notify`` runs in the same transaction as the insert."""

    def __init__(self, session: Session, notify_channel: str) -> None:
        self._s = session
        self._channel = notify_channel

    def append(
        self, topic: str, payload: Mapping[str, JsonValue], *, campaign_id: UUID | None = None
    ) -> int:
        row = EventRow(topic=topic, campaign_id=campaign_id, payload=dict(payload))
        self._s.add(row)
        execute(
            self._s,
            text("SELECT pg_notify(:channel, :payload)"),
            {"channel": self._channel, "payload": str(row.id)},
        )
        return int(row.id)

    def since(
        self, last_id: int, *, campaign_id: UUID | None = None, limit: int | None = None
    ) -> tuple[EventRecord, ...]:
        size = clamp_limit(limit)
        stmt = select(EventRow).where(EventRow.id > last_id).order_by(EventRow.id)
        if campaign_id is not None:
            stmt = stmt.where(EventRow.campaign_id == campaign_id)
        rows = self._s.scalars(stmt.limit(size)).all()
        return tuple(event_record(r) for r in rows)
