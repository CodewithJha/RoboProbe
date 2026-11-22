"""SQLAlchemy Idempotency-Key store (wired only from composition roots).

Implements: T-080d
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from roboprobe.core.idempotency import IdempotencyRecord
from roboprobe.store.orm import IdempotencyKeyRow

__all__ = ["SqlAlchemyIdempotencyStore"]


class SqlAlchemyIdempotencyStore:
    """Persist Idempotency-Key responses in PostgreSQL."""

    def __init__(self, factory: Callable[[], Session] | sessionmaker[Session]) -> None:
        """Bind to a session factory."""
        self._factory = factory

    def get(self, key: str) -> IdempotencyRecord | None:
        """Return the stored record for ``key``, or ``None``."""
        with self._factory() as session:
            row = session.get(IdempotencyKeyRow, key)
            if row is None:
                return None
            return IdempotencyRecord(
                key=row.key,
                method=row.method,
                path=row.path,
                body_sha256=row.body_sha256,
                status=row.status,
                response_json=row.response_json,
                created_at=row.created_at,
            )

    def put(self, record: IdempotencyRecord) -> None:
        """Insert or replace the record for ``record.key``."""
        with self._factory() as session:
            row = session.get(IdempotencyKeyRow, record.key)
            if row is None:
                session.add(
                    IdempotencyKeyRow(
                        key=record.key,
                        method=record.method,
                        path=record.path,
                        body_sha256=record.body_sha256,
                        status=record.status,
                        response_json=record.response_json,
                        created_at=record.created_at,
                    )
                )
            else:
                row.method = record.method
                row.path = record.path
                row.body_sha256 = record.body_sha256
                row.status = record.status
                row.response_json = record.response_json
                row.created_at = record.created_at
            session.commit()

    def delete_older_than(self, cutoff: datetime) -> int:
        """Delete rows with ``created_at < cutoff``; return deleted count."""
        with self._factory() as session:
            result = session.execute(
                delete(IdempotencyKeyRow).where(IdempotencyKeyRow.created_at < cutoff)
            )
            session.commit()
            return int(getattr(result, "rowcount", 0) or 0)
