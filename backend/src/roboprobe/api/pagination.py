"""Opaque keyset cursors and page DTOs (docs/12 §1).

Implements: T-080d, FR-API-001, NFR-PERF-004
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, tuple_
from sqlalchemy.sql import ColumnElement

from roboprobe.core.errors import ErrorCode, ValidationError

__all__ = [
    "Cursor",
    "Page",
    "apply_keyset",
    "clamp_limit",
    "decode_cursor",
    "encode_cursor",
]

_HMAC_HEX_LEN = 16
_CURSOR_SEP = "."


class Page[T](BaseModel):
    """One page of items plus an opaque cursor for the next page."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[T]
    next_cursor: str | None = None


class Cursor(BaseModel):
    """Decoded keyset cursor payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sort_values: tuple[Any, ...]
    id: UUID


def clamp_limit(limit: int | None, *, default: int, maximum: int) -> int:
    """Return a page size in ``[1, maximum]`` (values above max are clamped)."""
    value = default if limit is None else limit
    if value < 1:
        msg = "limit must be >= 1"
        raise ValidationError(msg, code=ErrorCode.VALIDATION_ERROR, context={"limit": value})
    return min(value, maximum)


def encode_cursor(sort_values: tuple[Any, ...], item_id: UUID, *, secret: str) -> str:
    """Encode ``(sort_values, id)`` as base64url JSON plus a truncated HMAC tag."""
    payload = {"v": list(sort_values), "id": str(item_id)}
    raw = json.dumps(payload, separators=(",", ":"), default=str).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{body}{_CURSOR_SEP}{_sign(body, secret)}"


def decode_cursor(token: str, *, secret: str) -> Cursor:
    """Decode and verify a cursor; tampering yields ``VALIDATION_ERROR``."""
    try:
        body, tag = token.rsplit(_CURSOR_SEP, 1)
    except ValueError as exc:
        msg = "malformed cursor"
        raise ValidationError(msg, code=ErrorCode.VALIDATION_ERROR) from exc
    if not hmac.compare_digest(tag, _sign(body, secret)):
        msg = "tampered or expired cursor"
        raise ValidationError(msg, code=ErrorCode.VALIDATION_ERROR)
    pad = "=" * (-len(body) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(body + pad))
        return Cursor(sort_values=tuple(data["v"]), id=UUID(data["id"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        msg = "malformed cursor payload"
        raise ValidationError(msg, code=ErrorCode.VALIDATION_ERROR) from exc


def apply_keyset(
    stmt: Select[Any],
    sort_cols: Sequence[ColumnElement[Any]],
    cursor: Cursor | None,
    *,
    limit: int,
    descending: bool = True,
) -> Select[Any]:
    """Append keyset ``WHERE (sort…, id) </> (:k…, :id)`` and fetch ``limit + 1`` rows."""
    if cursor is not None:
        keys = (*cursor.sort_values, cursor.id)
        cmp = tuple_(*sort_cols) < keys if descending else tuple_(*sort_cols) > keys
        stmt = stmt.where(cmp)
    return stmt.limit(limit + 1)


def _sign(body: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return digest[:_HMAC_HEX_LEN]
