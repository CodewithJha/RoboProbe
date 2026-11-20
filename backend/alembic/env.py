"""Alembic environment: URL from ``load_settings()`` (docs/11 §8, docs/27 §6)."""

from __future__ import annotations

from logging.config import fileConfig
from typing import Literal

from alembic import context
from sqlalchemy import Engine
from sqlalchemy.engine import Connection

from roboprobe.core.settings import load_settings
from roboprobe.store.engine import create_engine_from_settings
from roboprobe.store.orm import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _engine() -> Engine:
    return create_engine_from_settings(load_settings().database)


def run_migrations_offline() -> None:
    """Emit SQL without a live connection."""
    url = load_settings().database.url.get_secret_value()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the configured database."""
    connectable = context.config.attributes.get("connection")
    if isinstance(connectable, Connection):
        _configure_and_run(connectable)
        return
    engine = _engine()
    with engine.connect() as connection:
        _configure_and_run(connection)
    engine.dispose()


def _configure_and_run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations(mode: Literal["online", "offline"] | None = None) -> None:
    """Entry used by Alembic and tests."""
    if mode == "offline" or (mode is None and context.is_offline_mode()):
        run_migrations_offline()
        return
    run_migrations_online()


run_migrations()
