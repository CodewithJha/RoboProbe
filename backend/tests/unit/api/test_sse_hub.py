"""SSE hub and /events routing without PostgreSQL (T-083a, T-083b)."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from roboprobe.api.routers import events as events_router
from roboprobe.api.sse import (
    RESYNC_EVENT,
    EventHub,
    OutboxEvent,
    _event_from_row,
    _jsonable,
    _psycopg_conninfo,
)
from roboprobe.core.metrics_registry import create_metrics
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.settings.api import SseSettings

pytestmark = pytest.mark.unit


def _settings(**sse: object) -> RoboProbeSettings:
    body: dict[str, object] = {
        "poll_interval_s": 0.01,
        "queue_size": 1,
        "reconnect_initial_s": 0.01,
        "reconnect_max_s": 0.02,
        "batch_size": 2,
        "connect_timeout_s": 1.0,
        "ping_interval_s": 0.2,
    }
    body.update(sse)
    return RoboProbeSettings(
        database={"url": "postgresql+psycopg://roboprobe:pw@127.0.0.1:5432/roboprobe"},
        api={"sse": body},
        observability={"metrics_enabled": True},
    )


class _Script:
    def __init__(self) -> None:
        self.rows: list[list[tuple[object, ...]]] = []
        self.fetch_error: BaseException | None = None
        self.listen_error: BaseException | None = None
        self.connected: list[_Conn] = []


class _Cursor:
    def __init__(self, script: _Script) -> None:
        self._script = script

    async def __aenter__(self) -> _Cursor:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def execute(self, _statement: object, _params: object = ()) -> None:
        if self._script.fetch_error is not None:
            error = self._script.fetch_error
            self._script.fetch_error = None
            raise error

    async def fetchall(self) -> list[tuple[object, ...]]:
        if self._script.rows:
            return self._script.rows.pop(0)
        return []


class _Conn:
    def __init__(self, script: _Script) -> None:
        self.script = script
        self.closed = False

    async def set_autocommit(self, _value: bool) -> None:
        return None

    def cursor(self) -> _Cursor:
        return _Cursor(self.script)

    async def execute(self, _query: object) -> None:
        if self.script.listen_error is not None:
            error = self.script.listen_error
            self.script.listen_error = None
            raise error

    def notifies(self) -> _Notes:
        return _Notes(self)

    async def close(self) -> None:
        self.closed = True


class _Notes:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    def __aiter__(self) -> _Notes:
        return self

    async def __anext__(self) -> object:
        if self._conn.closed:
            raise StopAsyncIteration
        await asyncio.sleep(0.05)
        if self._conn.closed:
            raise StopAsyncIteration
        return object()


def _patch_connect(monkeypatch: pytest.MonkeyPatch, script: _Script) -> None:
    async def connect(_dsn: str, **_kwargs: object) -> _Conn:
        conn = _Conn(script)
        script.connected.append(conn)
        return conn

    monkeypatch.setattr("roboprobe.api.sse.psycopg.AsyncConnection.connect", connect)


def test_conninfo_strips_driver_and_jsonable_values() -> None:
    dsn = _psycopg_conninfo("postgresql+psycopg://roboprobe:pw@127.0.0.1:5432/roboprobe")
    assert dsn.startswith("postgresql://")
    assert "+psycopg" not in dsn
    campaign = uuid4()
    assert _jsonable(None) is None
    assert _jsonable(True) is True
    assert _jsonable(campaign) == str(campaign)
    assert _jsonable({"k": [1, campaign]}) == {"k": [1, str(campaign)]}
    assert _jsonable({1}) == str({1})
    row = _event_from_row((4, "run.finished", None, {"n": 1}))
    assert row.campaign_id is None and row.payload == {"n": 1}
    as_uuid = _event_from_row((5, "run.finished", campaign, "nope"))
    assert as_uuid.campaign_id == campaign and as_uuid.payload == {}
    as_text = _event_from_row((6, "run.finished", str(campaign), {}))
    assert as_text.campaign_id == campaign


def test_backoff_settings_reject_inverted_delays() -> None:
    with pytest.raises(ValueError, match="reconnect_initial_s"):
        SseSettings(reconnect_initial_s=2.0, reconnect_max_s=1.0)


def test_queue_overflow_and_campaign_filter() -> None:
    hub = EventHub(_settings(), create_metrics(enabled=True))
    wanted = uuid4()
    sub = hub.subscribe(wanted, None)
    other = hub.subscribe(None, 0)
    hub._fanout(OutboxEvent(1, "run.finished", {"n": 1}, wanted))
    hub._fanout(OutboxEvent(2, "run.finished", {"n": 2}, uuid4()))
    hub._fanout(OutboxEvent(3, "run.finished", {"n": 3}, wanted))
    hub.detach(sub._subscriber)
    hub.detach(sub._subscriber)
    assert other._subscriber in hub._subscribers
    assert sub._subscriber not in hub._subscribers


def test_subscription_backlog_live_resync_and_close() -> None:
    hub = EventHub(_settings(queue_size=8), create_metrics(enabled=True))
    campaign = uuid4()

    async def scenario() -> None:
        pages = [
            [
                OutboxEvent(2, "run.started", {"n": 1}, campaign),
                OutboxEvent(3, "run.finished", {"n": 2}, campaign),
            ]
        ]

        async def fetch_after(last_id: int, campaign_id: UUID | None) -> list[OutboxEvent]:
            assert campaign_id == campaign
            assert last_id in {1, 3}
            return pages.pop(0) if pages else []

        hub.fetch_after = fetch_after  # type: ignore[method-assign]
        subscription = hub.subscribe(campaign, 1)
        assert subscription.__aiter__() is subscription
        assert (await anext(subscription)).id == 2
        assert (await anext(subscription)).id == 3
        subscription._subscriber.queue.put_nowait(OutboxEvent(3, "run.finished", {}, campaign))
        subscription._subscriber.queue.put_nowait(
            OutboxEvent(4, "run.finished", {"n": 4}, campaign)
        )
        assert (await anext(subscription)).id == 4
        subscription._subscriber.queue.put_nowait(
            OutboxEvent(0, RESYNC_EVENT, {"reason": "overflow"}, campaign)
        )
        assert (await anext(subscription)).type == RESYNC_EVENT
        await subscription.aclose()
        await subscription.aclose()
        with pytest.raises(StopAsyncIteration):
            await anext(subscription)

    asyncio.run(scenario())


def test_empty_backlog_then_live_event() -> None:
    hub = EventHub(_settings(queue_size=4), create_metrics(enabled=True))

    async def scenario() -> None:
        async def fetch_after(_last_id: int, _campaign_id: UUID | None) -> list[OutboxEvent]:
            return []

        hub.fetch_after = fetch_after  # type: ignore[method-assign]
        subscription = hub.subscribe(None, 0)
        subscription._subscriber.queue.put_nowait(OutboxEvent(8, "alert", {"m": "x"}, None))
        event = await anext(subscription)
        assert event.id == 8
        await subscription.aclose()

    asyncio.run(scenario())


def test_hub_start_stop_poll_and_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    script = _Script()
    script.rows = [[(4,)], [(9, "run.finished", None, {"n": 1})]]
    script.listen_error = RuntimeError("listen down")
    _patch_connect(monkeypatch, script)
    hub = EventHub(_settings(), create_metrics(enabled=True))

    async def scenario() -> None:
        subscription = hub.subscribe(None, None)
        await hub.start()
        await hub.start()
        event = await asyncio.wait_for(anext(subscription), timeout=2)
        assert event.id == 9
        await hub.drop_listen()
        script.fetch_error = RuntimeError("poll down")
        await asyncio.sleep(0.05)
        await hub.stop()
        assert hub._tasks == []
        await hub._close_query()

    asyncio.run(scenario())


def test_start_when_cursor_read_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    script = _Script()
    script.fetch_error = RuntimeError("db down")
    _patch_connect(monkeypatch, script)
    hub = EventHub(_settings(), create_metrics(enabled=True))

    async def scenario() -> None:
        await hub.start()
        assert hub._cursor == 0
        await hub.stop()

    asyncio.run(scenario())


def test_connect_and_fetch_after(monkeypatch: pytest.MonkeyPatch) -> None:
    script = _Script()
    script.rows = [[(3, "run.finished", None, {"ok": True})]]
    _patch_connect(monkeypatch, script)
    hub = EventHub(_settings(), create_metrics(enabled=True))

    async def scenario() -> None:
        conn = await hub._connect()
        assert conn in script.connected
        rows = await hub.fetch_after(1, None)
        assert rows[0].id == 3
        assert await hub._max_id() == 0
        await hub._close_query()

    asyncio.run(scenario())


def test_events_route_resume_header_and_ping() -> None:
    hub = EventHub(_settings(), create_metrics(enabled=True))
    seen: list[tuple[object, object]] = []

    class _Sub:
        def __init__(self) -> None:
            self._sent = False

        def __aiter__(self) -> _Sub:
            return self

        async def __anext__(self) -> OutboxEvent:
            if self._sent:
                await asyncio.sleep(30)
            self._sent = True
            return OutboxEvent(7, "run.finished", {"n": 1}, None)

        async def aclose(self) -> None:
            return None

    def subscribe(campaign_id: object, last_event_id: object) -> _Sub:
        seen.append((campaign_id, last_event_id))
        return _Sub()

    hub.subscribe = subscribe  # type: ignore[method-assign]
    app = FastAPI()
    app.include_router(events_router.router)
    app.state.event_hub = hub
    app.state.settings = _settings()
    with TestClient(app) as client:
        bad = client.get("/events", headers={"Last-Event-ID": "nope"})
        assert bad.status_code == 400
        with client.stream(
            "GET",
            "/events",
            params={"last_event_id": 1},
            headers={"Last-Event-ID": "3"},
        ) as response:
            assert response.status_code == 200
            body_lines: list[str] = []
            for line in response.iter_lines():
                body_lines.append(line)
                if "run.finished" in line:
                    break
        assert any("run.finished" in line for line in body_lines)
        assert seen[-1] == (None, 3)
        with client.stream("GET", "/events", params={"last_event_id": 2}) as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if line.startswith(":"):
                    assert "ping" in line
                    break
            else:
                pytest.fail("expected a ping comment")
