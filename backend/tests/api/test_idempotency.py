"""Idempotency-Key helpers (T-080d)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from roboprobe.api.idempotency import (
    IdempotencyRecord,
    body_sha256,
    purge_expired,
    remember,
    replay_or_begin,
)
from roboprobe.core.errors import ErrorCode, ValidationError

pytestmark = pytest.mark.unit


class MemoryStore:
    """In-memory IdempotencyStore for unit tests."""

    def __init__(self) -> None:
        """Create an empty store."""
        self.rows: dict[str, IdempotencyRecord] = {}

    def get(self, key: str) -> IdempotencyRecord | None:
        """Return a cached record."""
        return self.rows.get(key)

    def put(self, record: IdempotencyRecord) -> None:
        """Store a record."""
        self.rows[record.key] = record

    def delete_older_than(self, cutoff: datetime) -> int:
        """Drop expired rows."""
        before = len(self.rows)
        self.rows = {k: v for k, v in self.rows.items() if v.created_at >= cutoff}
        return before - len(self.rows)


def test_replay_same_key() -> None:
    store = MemoryStore()
    now = datetime(2024, 1, 1, tzinfo=UTC)
    body = b'{"a":1}'
    remember(
        store,
        key="k1",
        method="POST",
        path="/api/v1/campaigns",
        body=body,
        status=201,
        response_json={"id": "x"},
        created_at=now,
    )
    replay = replay_or_begin(store, key="k1", method="POST", path="/api/v1/campaigns", body=body)
    assert replay is not None
    assert replay.status == 201
    assert replay.response_json == {"id": "x"}


def test_same_key_different_body() -> None:
    store = MemoryStore()
    now = datetime(2024, 1, 1, tzinfo=UTC)
    remember(
        store,
        key="k1",
        method="POST",
        path="/api/v1/campaigns",
        body=b'{"a":1}',
        status=201,
        response_json={},
        created_at=now,
    )
    with pytest.raises(ValidationError) as exc:
        replay_or_begin(store, key="k1", method="POST", path="/api/v1/campaigns", body=b'{"a":2}')
    assert exc.value.code is ErrorCode.VALIDATION_ERROR


def test_purge_expired() -> None:
    store = MemoryStore()
    store.put(
        IdempotencyRecord(
            key="old",
            method="POST",
            path="/x",
            body_sha256=body_sha256(b"{}"),
            status=200,
            response_json={},
            created_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
    )
    deleted = purge_expired(store, now=datetime(2024, 1, 1, tzinfo=UTC), ttl_s=86400)
    assert deleted == 1
    assert store.get("old") is None
