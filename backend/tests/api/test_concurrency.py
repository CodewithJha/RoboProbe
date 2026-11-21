"""ETag / If-Match helpers (T-080d)."""

from __future__ import annotations

import pytest

from roboprobe.api.concurrency import assert_if_match, etag_matches, format_etag, parse_etag
from roboprobe.core.errors import ErrorCode, ValidationError

pytestmark = pytest.mark.unit


def test_format_and_parse() -> None:
    assert format_etag(3) == 'W/"3"'
    assert parse_etag('W/"3"') == 3
    assert parse_etag('"3"') == 3


def test_missing_if_match() -> None:
    with pytest.raises(ValidationError) as exc:
        assert_if_match(None, 1)
    assert exc.value.code is ErrorCode.PRECONDITION_FAILED


def test_stale_etag() -> None:
    with pytest.raises(ValidationError) as exc:
        assert_if_match('W/"1"', 2)
    assert exc.value.code is ErrorCode.PRECONDITION_FAILED


def test_matching_etag() -> None:
    assert_if_match('W/"2"', 2)
    assert etag_matches("*", 99)
