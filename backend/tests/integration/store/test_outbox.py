"""Transactional outbox + NOTIFY (T-011c)."""

from __future__ import annotations

from collections.abc import Callable

import psycopg
import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from roboprobe.store.events import TOPIC_ALERT
from roboprobe.store.orm import Base
from roboprobe.store.uow import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.integration


def test_rollback_emits_nothing(uow_factory: Callable[[], SqlAlchemyUnitOfWork]) -> None:
    with pytest.raises(RuntimeError, match="abort"), uow_factory() as uow:
        uow.events.append(TOPIC_ALERT, {"level": "error", "code": "X", "message": "m"})
        raise RuntimeError("abort")
    with uow_factory() as uow:
        assert uow.events.since(0) == ()


def test_since_orders_by_id(uow_factory: Callable[[], SqlAlchemyUnitOfWork]) -> None:
    with uow_factory() as uow:
        first = uow.events.append(TOPIC_ALERT, {"level": "info", "code": "A", "message": "a"})
        second = uow.events.append(TOPIC_ALERT, {"level": "info", "code": "B", "message": "b"})
        rows = uow.events.since(0)
        assert [r.id for r in rows] == [first, second]
        assert uow.events.since(first)[0].id == second


def test_notify_after_commit(pg_engine: Engine) -> None:
    Base.metadata.create_all(pg_engine)
    factory = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)
    url = pg_engine.url.render_as_string(hide_password=False).replace(
        "postgresql+psycopg", "postgresql"
    )
    with psycopg.connect(url) as listener:
        listener.execute("LISTEN roboprobe_events")
        listener.commit()
        with SqlAlchemyUnitOfWork(factory, notify_channel="roboprobe_events") as uow:
            event_id = uow.events.append(
                TOPIC_ALERT, {"level": "warning", "code": "DISK_LOW", "message": "low"}
            )
        payload = None
        for notify in listener.notifies(timeout=2.0):
            payload = notify.payload
            break
        assert payload == str(event_id)
    with SqlAlchemyUnitOfWork(factory, notify_channel="roboprobe_events") as uow:
        assert any(r.id == event_id for r in uow.events.since(0))
