"""Cursor pagination helpers (T-080d)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from roboprobe.api.pagination import (
    Page,
    clamp_limit,
    decode_cursor,
    encode_cursor,
)
from roboprobe.core.errors import ValidationError

pytestmark = pytest.mark.unit

SECRET = "unit-test-cursor-secret"


def test_clamp_limit() -> None:
    assert clamp_limit(None, default=50, maximum=500) == 50
    assert clamp_limit(1000, default=50, maximum=500) == 500
    with pytest.raises(ValidationError):
        clamp_limit(0, default=50, maximum=500)


def test_cursor_roundtrip() -> None:
    item_id = uuid4()
    token = encode_cursor(("2024-01-01T00:00:00Z",), item_id, secret=SECRET)
    cursor = decode_cursor(token, secret=SECRET)
    assert cursor.id == item_id
    assert cursor.sort_values == ("2024-01-01T00:00:00Z",)


def test_tampered_cursor() -> None:
    item_id = uuid4()
    token = encode_cursor((1,), item_id, secret=SECRET)
    with pytest.raises(ValidationError, match="tampered"):
        decode_cursor(token + "x", secret=SECRET)


def test_keyset_pages_cover_1000_ids() -> None:
    """Walking keyset pages of size 50 yields every id exactly once in order."""
    ordered = [UUID(int=i) for i in range(1, 1001)]
    page_size = 50
    seen: list[UUID] = []
    cursor_token: str | None = None
    while True:
        start = 0
        if cursor_token is not None:
            cur = decode_cursor(cursor_token, secret=SECRET)
            start = next(i for i, item in enumerate(ordered) if item == cur.id) + 1
        chunk = ordered[start : start + page_size]
        seen.extend(chunk)
        if len(chunk) < page_size:
            break
        cursor_token = encode_cursor((str(chunk[-1]),), chunk[-1], secret=SECRET)
    assert seen == ordered
    assert len(seen) == 1000


@given(st.lists(st.uuids(), min_size=1, max_size=80, unique=True))
@settings(max_examples=20, deadline=None)
def test_keyset_pages_property(ids: list) -> None:
    ordered = sorted(ids, key=str)
    page_size = 7
    seen: list = []
    cursor_token: str | None = None
    while True:
        start = 0
        if cursor_token is not None:
            cur = decode_cursor(cursor_token, secret=SECRET)
            start = next(i for i, item in enumerate(ordered) if item == cur.id) + 1
        chunk = ordered[start : start + page_size]
        seen.extend(chunk)
        if len(chunk) < page_size:
            break
        cursor_token = encode_cursor((str(chunk[-1]),), chunk[-1], secret=SECRET)
    assert seen == ordered


def test_page_model() -> None:
    page = Page[int](items=[1, 2], next_cursor=None)
    assert page.items == [1, 2]
