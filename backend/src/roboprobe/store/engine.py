"""SQLAlchemy engine factory from :class:`~roboprobe.core.settings.DatabaseSettings`.

Layer: Adapter (infrastructure).
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from roboprobe.core.settings.database import DatabaseSettings

__all__ = ["SessionFactory", "create_engine_from_settings", "session_factory"]

SessionFactory = Callable[[], Session]


def create_engine_from_settings(settings: DatabaseSettings) -> Engine:
    """Build a pooled engine with the configured statement timeout."""
    return create_engine(
        settings.url.get_secret_value(),
        pool_size=settings.pool_size,
        pool_pre_ping=True,
        connect_args={"options": f"-c statement_timeout={settings.statement_timeout_ms}"},
    )


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a sessionmaker bound to ``engine`` (one session per Unit of Work)."""
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
