"""PostgreSQL advisory locks for campaign leadership (docs/05 §5.1).

Implements: T-041b, NFR-REL-002
"""

from __future__ import annotations

from types import TracebackType
from typing import Self
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

__all__ = ["AdvisoryLock", "campaign_lock_key"]


def campaign_lock_key(campaign_id: UUID) -> str:
    """Return the opaque key hashed by Postgres ``hashtext`` for ``campaign_id``."""
    return str(campaign_id)


class AdvisoryLock:
    """Session-level advisory lock held on a dedicated connection for the loop lifetime.

    Uses ``pg_try_advisory_lock(hashtext(:key))`` so two orchestrators never drive the
    same campaign (NFR-REL-002).
    """

    def __init__(self, engine: Engine, key: str) -> None:
        """Bind an engine and lock key; acquire with :meth:`acquire` or ``with``."""
        self._engine = engine
        self._key = key
        self._conn: Connection | None = None
        self.held = False

    def acquire(self) -> bool:
        """Try to acquire the lock; return whether it was obtained."""
        if self.held:
            return True
        conn = self._engine.connect()
        row = conn.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": self._key}
        ).scalar_one()
        if not bool(row):
            conn.close()
            return False
        self._conn = conn
        self.held = True
        return True

    def release(self) -> None:
        """Release the lock and close the dedicated connection."""
        if self._conn is None:
            self.held = False
            return
        try:
            self._conn.execute(
                text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": self._key}
            )
            self._conn.commit()
        finally:
            self._conn.close()
            self._conn = None
            self.held = False

    def __enter__(self) -> Self:
        """Acquire or raise if the lock is held elsewhere."""
        if not self.acquire():
            msg = f"could not acquire advisory lock for {self._key}"
            raise RuntimeError(msg)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Release the lock."""
        del exc_type, exc, tb
        self.release()
