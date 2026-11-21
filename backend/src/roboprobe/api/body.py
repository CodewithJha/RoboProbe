"""Bounded request-body reading for upload endpoints (docs/12 §2, TM-02, TM-13).

The limit is checked while streaming, before any YAML/JSON parsing, so an oversized body is
rejected with HTTP 413 without being buffered in full.

Layer: Interface (L4).

Implements: T-081a, NFR-SEC-001
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from roboprobe.core.settings import RoboProbeSettings

__all__ = ["BYTES_PER_MB", "max_upload_bytes", "read_upload"]

BYTES_PER_MB = 1024 * 1024
"""Bytes in one mebibyte; ``api.max_upload_mb`` is expressed in MB."""


def max_upload_bytes(settings: RoboProbeSettings) -> int:
    """Return ``api.max_upload_mb`` in bytes."""
    return settings.api.max_upload_mb * BYTES_PER_MB


async def read_upload(request: Request, *, max_bytes: int) -> bytes:
    """Read the request body, rejecting more than ``max_bytes`` with HTTP 413.

    Raises:
        fastapi.HTTPException: Status 413 when the streamed body exceeds the limit.
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            detail = f"request body exceeds api.max_upload_mb ({max_bytes} bytes)"
            raise HTTPException(status_code=413, detail=detail)
        chunks.append(chunk)
    return b"".join(chunks)
