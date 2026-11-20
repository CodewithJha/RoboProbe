"""Keyset pagination helper used by list repositories (docs/12 §1).

Layer: Adapter (infrastructure).
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from roboprobe.core.errors import ValidationError

__all__ = ["DEFAULT_PAGE_LIMIT", "MAX_PAGE_LIMIT", "Page", "clamp_limit"]

DEFAULT_PAGE_LIMIT = 50
"""Default page size (docs/12 §1)."""
MAX_PAGE_LIMIT = 500
"""Maximum page size (docs/12 §1)."""


class Page[T](BaseModel):
    """One page of records plus an opaque cursor for the next page."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[T, ...]
    next_cursor: str | None = None


def clamp_limit(limit: int | None) -> int:
    """Return a page size in ``[1, MAX_PAGE_LIMIT]``.

    Raises:
        ValidationError: If ``limit`` is not positive.
    """
    value = DEFAULT_PAGE_LIMIT if limit is None else limit
    if value < 1:
        msg = "limit must be >= 1"
        raise ValidationError(msg, context={"limit": value})
    return min(value, MAX_PAGE_LIMIT)


def extra_item[T](rows: Sequence[T], limit: int) -> tuple[tuple[T, ...], T | None]:
    """Split ``limit + 1`` fetched rows into a page and the keyset sentinel."""
    if len(rows) > limit:
        return tuple(rows[:limit]), rows[limit]
    return tuple(rows), None
