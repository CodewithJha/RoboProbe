"""Fixtures for runner integration tests."""

from __future__ import annotations

import sys
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import sessionmaker

from roboprobe.core.logging import configure_logging
from roboprobe.core.settings import LoggingSettings
from roboprobe.store.orm import Base
from roboprobe.store.uow import SqlAlchemyUnitOfWork

NOTIFY_CHANNEL = "roboprobe_events"


@pytest.fixture(autouse=True)
def _reset_structlog_stream() -> None:
    """Rebind structlog after CliRunner closes its capture stream."""
    configure_logging(LoggingSettings(), "test-runner", "0.0.0", stream=sys.stderr)


@pytest.fixture
def uow_factory(pg_engine) -> Iterator:
    Base.metadata.drop_all(pg_engine)
    Base.metadata.create_all(pg_engine)
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)

    def make() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(factory, notify_channel=NOTIFY_CHANNEL)

    yield make


@pytest.fixture
def session_factory(pg_engine):
    Base.metadata.drop_all(pg_engine)
    Base.metadata.create_all(pg_engine)
    return sessionmaker(bind=pg_engine, expire_on_commit=False)
