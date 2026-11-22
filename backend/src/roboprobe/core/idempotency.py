"""Idempotency-Key helpers and store protocol (docs/12 §1).

The concrete SQLAlchemy store lives in ``roboprobe.store`` and is wired via bootstrap;
this module stays free of ``store`` imports (docs/16 §2).

Implements: T-080d
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from roboprobe.core.errors import ErrorCode, ValidationError

__all__ = [
    "IdempotencyRecord",
    "IdempotencyStore",
    "body_sha256",
    "purge_expired",
    "remember",
    "replay_or_begin",
]


class IdempotencyRecord(BaseModel):
    """Cached response for one Idempotency-Key."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    method: str
    path: str
    body_sha256: str
    status: int
    response_json: dict[str, Any] | list[Any] | None
    created_at: datetime


class IdempotencyStore(Protocol):
    """Persistence for idempotent POST responses."""

    def get(self, key: str) -> IdempotencyRecord | None:
        """Return the stored record for ``key``, or ``None``."""

    def put(self, record: IdempotencyRecord) -> None:
        """Insert or replace the record for ``record.key``."""

    def delete_older_than(self, cutoff: datetime) -> int:
        """Delete rows with ``created_at < cutoff``; return deleted count."""


def body_sha256(body: bytes) -> str:
    """Hex SHA-256 of a request body."""
    return hashlib.sha256(body).hexdigest()


def replay_or_begin(
    store: IdempotencyStore,
    *,
    key: str,
    method: str,
    path: str,
    body: bytes,
) -> IdempotencyRecord | None:
    """Return a prior response for ``key``, or ``None`` to proceed with the handler.

    Raises:
        ValidationError: Same key was used with a different body.
    """
    existing = store.get(key)
    if existing is None:
        return None
    digest = body_sha256(body)
    if existing.body_sha256 != digest or existing.method != method or existing.path != path:
        msg = "Idempotency-Key reused with a different request"
        raise ValidationError(msg, code=ErrorCode.VALIDATION_ERROR, context={"key": key})
    return existing


def remember(  # noqa: PLR0913 - cached response fields
    store: IdempotencyStore,
    *,
    key: str,
    method: str,
    path: str,
    body: bytes,
    status: int,
    response_json: Mapping[str, Any] | list[Any] | None,
    created_at: datetime,
) -> IdempotencyRecord:
    """Persist the handler response under ``key``."""
    record = IdempotencyRecord(
        key=key,
        method=method,
        path=path,
        body_sha256=body_sha256(body),
        status=status,
        response_json=dict(response_json) if isinstance(response_json, Mapping) else response_json,
        created_at=created_at,
    )
    store.put(record)
    return record


def purge_expired(store: IdempotencyStore, *, now: datetime, ttl_s: int) -> int:
    """Delete keys older than ``ttl_s`` (orchestrator maintenance hook)."""
    return store.delete_older_than(now - timedelta(seconds=ttl_s))
