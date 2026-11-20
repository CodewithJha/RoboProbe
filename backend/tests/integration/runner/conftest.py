"""Fixtures for runner integration tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import sessionmaker

from roboprobe.store.orm import Base
from roboprobe.store.uow import SqlAlchemyUnitOfWork

NOTIFY_CHANNEL = "roboprobe_events"


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
