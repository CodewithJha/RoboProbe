"""Postgres fixtures for store integration tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker

from roboprobe.store.orm import Base
from roboprobe.store.uow import SqlAlchemyUnitOfWork

NOTIFY_CHANNEL = "roboprobe_events"


@pytest.fixture
def store_session(pg_connection) -> Iterator[Session]:
    Base.metadata.create_all(pg_connection)
    factory = sessionmaker(
        bind=pg_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def uow_factory(pg_connection) -> Iterator:
    Base.metadata.create_all(pg_connection)
    factory = sessionmaker(
        bind=pg_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    def make() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(factory, notify_channel=NOTIFY_CHANNEL)

    yield make


@pytest.fixture
def session_factory(pg_connection):
    Base.metadata.create_all(pg_connection)
    return sessionmaker(
        bind=pg_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
