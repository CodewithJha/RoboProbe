"""Outbox EventHub delivery, reconnect, and SSE resume (T-083a, T-083b)."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from roboprobe.api.app import create_app
from roboprobe.api.sse import RESYNC_EVENT, EventHub
from roboprobe.core.metrics_registry import create_metrics
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.store.orm import Base
from roboprobe.store.repositories.events import SqlEventRepo

pytestmark = pytest.mark.integration

_URL = "postgresql+psycopg://roboprobe@127.0.0.1:5432/roboprobe"


@pytest.fixture
def engine() -> Iterator[Engine]:
    try:
        eng = create_engine(_URL, pool_pre_ping=True)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(text("TRUNCATE events RESTART IDENTITY"))
    try:
        yield eng
    finally:
        eng.dispose()


def _settings(**sse: object) -> RoboProbeSettings:
    body: dict[str, object] = {
        "poll_interval_s": 0.05,
        "queue_size": 8,
        "reconnect_initial_s": 30.0,
        "reconnect_max_s": 30.0,
        "batch_size": 50,
        "connect_timeout_s": 5.0,
        "ping_interval_s": 15.0,
    }
    body.update(sse)
    return RoboProbeSettings(
        database={"url": _URL, "notify_channel": "roboprobe_events"},
        api={"host": "127.0.0.1", "sse": body},
        observability={"metrics_enabled": True},
    )


def _insert(
    engine: Engine,
    topic: str,
    payload: dict[str, object],
    campaign_id: UUID | None = None,
) -> int:
    factory = sessionmaker(bind=engine)
    with factory() as session:
        repo = SqlEventRepo(session, "roboprobe_events")
        event_id = repo.append(topic, payload, campaign_id=campaign_id)  # type: ignore[arg-type]
        session.commit()
        return event_id


async def _collect(hub: EventHub, last: int | None, count: int) -> list[int]:
    subscription = hub.subscribe(None, last)
    try:
        found: list[int] = []
        for _ in range(count):
            event = await asyncio.wait_for(anext(subscription), timeout=5)
            found.append(event.id)
        return found
    finally:
        await subscription.aclose()


def test_backlog_is_ordered_and_complete(engine: Engine) -> None:
    ids = [_insert(engine, "run.finished", {"n": index}) for index in range(3)]

    async def scenario() -> list[int]:
        hub = EventHub(_settings(), create_metrics(enabled=True))
        await hub.start()
        try:
            return await _collect(hub, 0, 3)
        finally:
            await hub.stop()

    assert asyncio.run(scenario()) == ids


def test_poll_delivers_after_listen_drops(engine: Engine) -> None:
    async def scenario() -> tuple[list[int], bytes]:
        metrics = create_metrics(enabled=True)
        hub = EventHub(_settings(), metrics)
        await hub.start()
        subscription = hub.subscribe(None, None)
        try:
            for _ in range(40):
                if hub._listen_conn is not None:
                    break
                await asyncio.sleep(0.05)
            await hub.drop_listen()
            await asyncio.sleep(0.1)
            _insert(engine, "alert", {"level": "warning", "message": "still-here"})
            event = await asyncio.wait_for(anext(subscription), timeout=5)
            return [event.id], metrics.exposition()
        finally:
            await subscription.aclose()
            await hub.stop()

    ids, exposition = asyncio.run(scenario())
    assert ids == [1]
    samples = [
        line
        for line in exposition.splitlines()
        if line.startswith(b"roboprobe_sse_reconnects_total ")
    ]
    assert samples
    assert float(samples[-1].split()[-1]) >= 1


def test_reconnect_does_not_duplicate_events(engine: Engine) -> None:
    async def scenario() -> tuple[int, int, str, str]:
        hub = EventHub(_settings(), create_metrics(enabled=True))
        await hub.start()
        subscription = hub.subscribe(None, 0)
        try:
            _insert(engine, "run.started", {"ordinal": 1})
            first = await asyncio.wait_for(anext(subscription), timeout=5)
            await hub.drop_listen()
            _insert(engine, "run.finished", {"ordinal": 2})
            second = await asyncio.wait_for(anext(subscription), timeout=5)
            return first.id, second.id, first.type, second.type
        finally:
            await subscription.aclose()
            await hub.stop()

    first_id, second_id, first_type, second_type = asyncio.run(scenario())
    assert first_id < second_id
    assert first_type != second_type


def test_slow_subscriber_does_not_block_a_consumer(engine: Engine) -> None:
    async def scenario() -> list[str]:
        hub = EventHub(_settings(queue_size=1), create_metrics(enabled=True))
        await hub.start()
        stalled = hub.subscribe(None, None)
        consumer = hub.subscribe(None, None)
        try:
            kinds: list[str] = []
            for index in range(4):
                _insert(engine, "run.finished", {"n": index})
                event = await asyncio.wait_for(anext(consumer), timeout=5)
                kinds.append(event.type)
            overflow = stalled._subscriber.queue
            assert overflow.qsize() <= 1
            if overflow.qsize() == 1:
                marker = overflow.get_nowait()
                assert marker.type == RESYNC_EVENT
            return kinds
        finally:
            await stalled.aclose()
            await consumer.aclose()
            await hub.stop()

    assert asyncio.run(scenario()) == ["run.finished"] * 4


def test_campaign_filter_and_header_resume(engine: Engine) -> None:
    wanted = uuid4()
    other = uuid4()
    _insert(engine, "run.finished", {"n": 1}, wanted)
    keep = _insert(engine, "run.finished", {"n": 2}, wanted)
    other_id = _insert(engine, "run.finished", {"n": 3}, other)
    app = create_app(_settings(ping_interval_s=0.2))
    with (
        TestClient(app) as client,
        client.stream(
            "GET",
            "/api/v1/events",
            params={"campaign_id": str(wanted), "last_event_id": 0},
            headers={"Last-Event-ID": str(keep - 1)},
        ) as response,
    ):
        assert response.status_code == 200
        ids: list[int] = []
        for line in response.iter_lines():
            if line.startswith("id:"):
                ids.append(int(line.split(":", 1)[1].strip()))
            if keep in ids:
                break
        assert keep in ids
        assert other_id not in ids
        assert all(event_id != keep - 1 for event_id in ids if event_id != 0)


def test_sse_latency_p95_under_two_seconds(engine: Engine) -> None:
    app = create_app(_settings())
    sent: list[float] = []

    def produce() -> None:
        time.sleep(0.3)
        for index in range(50):
            sent.append(time.perf_counter())
            _insert(engine, "run.finished", {"n": index})

    threading.Thread(target=produce, daemon=True).start()
    received: list[float] = []
    with (
        TestClient(app) as client,
        client.stream("GET", "/api/v1/events", params={"last_event_id": 0}, timeout=20) as response,
    ):
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data:"):
                received.append(time.perf_counter())
            if len(received) >= 50:
                break
    assert len(received) == 50
    assert len(sent) == 50
    deltas = sorted(recv - stamp for recv, stamp in zip(received, sent, strict=True))
    p95 = deltas[int(len(deltas) * 0.95) - 1]
    assert p95 < 2


def test_ping_comment(engine: Engine) -> None:
    app = create_app(_settings(ping_interval_s=0.2))
    with (
        TestClient(app) as client,
        client.stream("GET", "/api/v1/events", timeout=5) as response,
    ):
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith(":") and "ping" in line:
                return
    pytest.fail("expected a : ping comment")
