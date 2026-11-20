"""Flush pending ORM rows before Core SQL.

SQLAlchemy Core ``insert()`` / ``update()`` / ``delete()`` does not autoflush
the session, so parent rows added via ``Session.add`` are invisible to FK
checks and subsequent Core ``SELECT`` until flushed.

Implements: T-011a
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.engine import Result
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import Executable

__all__ = ["execute"]


def execute(
    session: Session,
    statement: Executable,
    parameters: Mapping[str, object] | None = None,
) -> Result[Any]:
    """Flush then execute ``statement`` on ``session``."""
    session.flush()
    if parameters is None:
        return session.execute(statement)
    return session.execute(statement, parameters)
