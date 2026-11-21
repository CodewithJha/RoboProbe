"""Streaming upload bounds stop receiving before parsing (T-081a, TM-13)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException, Request

from roboprobe.api.body import read_upload

pytestmark = pytest.mark.unit


def test_over_limit_stream_stops_reading() -> None:
    reads = 0

    async def receive() -> dict[str, object]:
        nonlocal reads
        reads += 1
        assert reads <= 2, "the oversized stream must not be drained"
        return {"type": "http.request", "body": b"abcd", "more_body": True}

    request = Request({"type": "http"}, receive=receive)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(read_upload(request, max_bytes=6))
    assert caught.value.status_code == 413
    assert reads == 2
