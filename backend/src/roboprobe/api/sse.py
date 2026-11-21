"""Outbox listener and in-process fan-out for server-sent events (docs/11 §4, docs/12 §4).

NOTIFY is only a wake-up. The ``events`` table is the source of truth, so a missed
notification is recovered on the next poll and delivery stays ordered.

Layer: Interface (L4).

Implements: T-083a, FR-API-002
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import psycopg
import structlog
from psycopg import sql

from roboprobe.core.metrics_registry import Metrics
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import JsonValue

__all__ = ["RESYNC_EVENT", "EventHub", "OutboxEvent", "Subscription"]

RESYNC_EVENT: Final = "resync"
"""Synthetic event queued when a subscriber falls behind (doc 13 §4)."""

_FETCH_ALL: Final = """
SELECT id, topic, campaign_id, payload
FROM events
WHERE id > %s
ORDER BY id
LIMIT %s
"""
_FETCH_FILTERED: Final = """
SELECT id, topic, campaign_id, payload
FROM events
WHERE id > %s AND (%s OR campaign_id = %s)
ORDER BY id
LIMIT %s
"""
_MAX_ID: Final = "SELECT COALESCE(MAX(id), 0) FROM events"

_log = structlog.get_logger("api.sse")


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    """One outbox row, or a synthetic ``resync`` marker.

    Attributes:
        id: ``events.id``; ``0`` for a synthetic resync.
        type: SSE event name (the outbox topic).
        payload: JSON object sent as the event ``data``.
        campaign_id: Campaign the row belongs to, when it has one.
    """

    id: int
    type: str
    payload: dict[str, JsonValue]
    campaign_id: UUID | None = None


@dataclass(slots=True)
class _Subscriber:
    campaign_id: UUID | None
    last_event_id: int | None
    queue: asyncio.Queue[OutboxEvent]


class Subscription:
    """Async iterator of outbox events for one subscriber.

    Backlog (``id`` greater than the resume cursor) is read from the table first.
    Live rows already placed on the queue are then yielded, skipping ids the
    backlog already produced. A ``resync`` marker is always yielded.
    """

    def __init__(self, hub: EventHub, subscriber: _Subscriber) -> None:
        """Bind one subscriber queue to ``hub``."""
        self._hub = hub
        self._subscriber = subscriber
        self._seen = 0 if subscriber.last_event_id is None else subscriber.last_event_id
        self._backlog_done = subscriber.last_event_id is None
        self._pending: list[OutboxEvent] = []
        self._closed = False

    def __aiter__(self) -> Subscription:
        """Return this iterator."""
        return self

    async def __anext__(self) -> OutboxEvent:
        """Yield the next backlog row, live row, or resync marker."""
        if self._closed:
            raise StopAsyncIteration
        if self._pending:
            return self._take(self._pending.pop(0))
        if not self._backlog_done:
            rows = await self._hub.fetch_after(self._seen, self._subscriber.campaign_id)
            if rows:
                self._pending.extend(rows)
                return self._take(self._pending.pop(0))
            self._backlog_done = True
        while True:
            event = await self._subscriber.queue.get()
            if event.type == RESYNC_EVENT:
                return event
            if event.id <= self._seen:
                continue
            return self._take(event)

    async def aclose(self) -> None:
        """Detach this subscriber so its queue no longer receives events."""
        if self._closed:
            return
        self._closed = True
        self._hub.detach(self._subscriber)

    def _take(self, event: OutboxEvent) -> OutboxEvent:
        self._seen = max(self._seen, event.id)
        return event


class EventHub:
    """LISTEN on the outbox channel and fan rows out to subscriber queues.

    Args:
        settings: Resolved settings (DSN, channel, SSE timings).
        metrics: Process metric set; client and reconnect counters are updated here.
    """

    def __init__(self, settings: RoboProbeSettings, metrics: Metrics) -> None:
        """Store settings and the metric set. Connections open in :meth:`start`."""
        self._settings = settings
        self._metrics = metrics
        self._conninfo = _psycopg_conninfo(settings.database.url.get_secret_value())
        self._channel = settings.database.notify_channel
        self._subscribers: list[_Subscriber] = []
        self._cursor = 0
        self._stopped = asyncio.Event()
        self._wake = asyncio.Event()
        self._query_lock = asyncio.Lock()
        self._tasks: list[asyncio.Task[None]] = []
        self._listen_conn: psycopg.AsyncConnection[Any] | None = None
        self._query_conn: psycopg.AsyncConnection[Any] | None = None

    async def start(self) -> None:
        """Start the LISTEN and poll tasks. A second call is a no-op."""
        if self._tasks:
            return
        self._stopped.clear()
        try:
            self._cursor = await self._max_id()
        except Exception as exc:
            self._cursor = 0
            _log.warning("sse.cursor_unavailable", error=exc.__class__.__name__)
        self._tasks = [
            asyncio.create_task(self._listen_loop(), name="sse-listen"),
            asyncio.create_task(self._poll_loop(), name="sse-poll"),
        ]
        self._metrics.sse_clients.set(len(self._subscribers))

    async def stop(self) -> None:
        """Cancel the background tasks and close both connections."""
        self._stopped.set()
        self._wake.set()
        listen = self._listen_conn
        if listen is not None and not listen.closed:
            await listen.close()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        await self._close_query()

    def subscribe(self, campaign_id: UUID | None, last_event_id: int | None) -> Subscription:
        """Register a subscriber.

        Args:
            campaign_id: When set, only events for that campaign are delivered.
            last_event_id: Resume after this id. ``None`` tails new events only.

        Returns:
            An async iterator of :class:`OutboxEvent`.
        """
        subscriber = _Subscriber(
            campaign_id=campaign_id,
            last_event_id=last_event_id,
            queue=asyncio.Queue(maxsize=self._settings.api.sse.queue_size),
        )
        self._subscribers.append(subscriber)
        self._metrics.sse_clients.set(len(self._subscribers))
        return Subscription(self, subscriber)

    def detach(self, subscriber: _Subscriber) -> None:
        """Remove ``subscriber`` and refresh the client gauge."""
        if subscriber in self._subscribers:
            self._subscribers.remove(subscriber)
        self._metrics.sse_clients.set(len(self._subscribers))

    async def drop_listen(self) -> None:
        """Close the LISTEN connection so delivery continues by polling."""
        listen = self._listen_conn
        if listen is not None and not listen.closed:
            await listen.close()

    async def fetch_after(self, last_id: int, campaign_id: UUID | None) -> list[OutboxEvent]:
        """Read the next backlog page after ``last_id``."""
        rows = await self._fetch(
            _FETCH_FILTERED,
            (last_id, campaign_id is None, campaign_id, self._settings.api.sse.batch_size),
        )
        return [_event_from_row(row) for row in rows]

    async def _listen_loop(self) -> None:
        delay = self._settings.api.sse.reconnect_initial_s
        while not self._stopped.is_set():
            if not await self._listen_or_fail():
                return
            self._metrics.sse_reconnects_total.inc()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopped.wait(), timeout=delay)
                return
            delay = min(delay * 2, self._settings.api.sse.reconnect_max_s)

    async def _listen_or_fail(self) -> bool:
        """Return True when LISTEN dropped and the loop should reconnect."""
        try:
            await self._listen_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._stopped.is_set():
                return False
            _log.warning("sse.listen_lost", error=exc.__class__.__name__)
            return True
        return not self._stopped.is_set()

    async def _listen_once(self) -> None:
        conn = await self._connect()
        self._listen_conn = conn
        try:
            await conn.set_autocommit(True)
            await conn.execute(sql.SQL("LISTEN {}").format(sql.Identifier(self._channel)))
            async for _notify in conn.notifies():
                self._wake.set()
                if self._stopped.is_set():
                    return
        finally:
            self._listen_conn = None
            if not conn.closed:
                await conn.close()

    async def _poll_loop(self) -> None:
        interval = self._settings.api.sse.poll_interval_s
        while not self._stopped.is_set():
            self._wake.clear()
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._stopped.is_set():
                    return
                _log.warning("sse.poll_failed", error=exc.__class__.__name__)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=interval)

    async def _poll_once(self) -> None:
        batch = self._settings.api.sse.batch_size
        while not self._stopped.is_set():
            rows = await self._fetch(_FETCH_ALL, (self._cursor, batch))
            if not rows:
                return
            for row in rows:
                event = _event_from_row(row)
                self._cursor = event.id
                self._fanout(event)
            if len(rows) < batch:
                return

    def _fanout(self, event: OutboxEvent) -> None:
        for subscriber in tuple(self._subscribers):
            if subscriber.campaign_id is not None and event.campaign_id != subscriber.campaign_id:
                continue
            self._offer(subscriber, event)

    def _offer(self, subscriber: _Subscriber, event: OutboxEvent) -> None:
        if _put_nowait(subscriber, event):
            return
        with contextlib.suppress(asyncio.QueueEmpty):
            subscriber.queue.get_nowait()
        resync = OutboxEvent(
            id=0,
            type=RESYNC_EVENT,
            payload={"reason": "overflow"},
            campaign_id=subscriber.campaign_id,
        )
        _put_nowait(subscriber, resync)
        _put_nowait(subscriber, event)

    async def _max_id(self) -> int:
        rows = await self._fetch(_MAX_ID, ())
        return int(rows[0][0]) if rows else 0

    async def _fetch(self, statement: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        async with self._query_lock:
            if self._query_conn is None or self._query_conn.closed:
                self._query_conn = await self._connect()
            try:
                async with self._query_conn.cursor() as cur:
                    await cur.execute(statement, params)
                    fetched = await cur.fetchall()
            except Exception:
                await self._close_query()
                raise
            return [tuple(row) for row in fetched]

    async def _connect(self) -> psycopg.AsyncConnection[Any]:
        timeout = max(1, int(self._settings.api.sse.connect_timeout_s))
        return await psycopg.AsyncConnection.connect(
            self._conninfo,
            autocommit=True,
            connect_timeout=timeout,
        )

    async def _close_query(self) -> None:
        conn = self._query_conn
        self._query_conn = None
        if conn is not None and not conn.closed:
            await conn.close()


def _put_nowait(subscriber: _Subscriber, event: OutboxEvent) -> bool:
    try:
        subscriber.queue.put_nowait(event)
    except asyncio.QueueFull:
        return False
    else:
        return True


def _psycopg_conninfo(url: str) -> str:
    """Strip a SQLAlchemy driver suffix so psycopg accepts the DSN."""
    parts = urlsplit(url)
    scheme = parts.scheme.split("+", 1)[0]
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


def _event_from_row(row: tuple[Any, ...]) -> OutboxEvent:
    raw_id, topic, campaign_id, payload = row
    cid: UUID | None
    if campaign_id is None:
        cid = None
    elif isinstance(campaign_id, UUID):
        cid = campaign_id
    else:
        cid = UUID(str(campaign_id))
    body = payload if isinstance(payload, Mapping) else {}
    return OutboxEvent(
        id=int(raw_id),
        type=str(topic),
        payload={str(key): _jsonable(value) for key, value in body.items()},
        campaign_id=cid,
    )


def _jsonable(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return str(value)
