"""Idempotency rows committed with their resource transaction (T-081b, FR-API-001)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from roboprobe.core.idempotency import IdempotencyRecord
from roboprobe.store.orm import IdempotencyKeyRow

__all__ = ["SqlIdempotencyRepo"]


class SqlIdempotencyRepo:
    """Reuse the request UoW session; never commit separately from its resource writes."""

    def __init__(self, session: Session) -> None:
        """Bind to the caller-owned transaction."""
        self._session = session

    def try_lock(self, key: str) -> bool:
        """Serialize matching keys until this resource transaction commits or rolls back."""
        return bool(
            self._session.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
                {"key": f"idempotency:{key}"},
            ).scalar_one()
        )

    def get(self, key: str) -> IdempotencyRecord | None:
        """Return a cached response from this transaction."""
        row = self._session.get(IdempotencyKeyRow, key)
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
        """Stage a response in the resource transaction without committing."""
        self._session.merge(IdempotencyKeyRow(**record.model_dump()))
        self._session.flush()

    def delete_older_than(self, cutoff: datetime) -> int:
        """Expire old responses in the resource transaction."""
        result = self._session.execute(
            delete(IdempotencyKeyRow).where(IdempotencyKeyRow.created_at < cutoff)
        )
        return int(getattr(result, "rowcount", 0) or 0)
