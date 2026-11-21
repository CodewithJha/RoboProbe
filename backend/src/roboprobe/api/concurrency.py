"""Weak ETag helpers and ``If-Match`` checks for mutable resources (docs/12 §1).

Implements: T-080d
"""

from __future__ import annotations

import re

from roboprobe.core.errors import ErrorCode, ValidationError

__all__ = [
    "assert_if_match",
    "etag_matches",
    "format_etag",
    "parse_etag",
]

_ETAG_RE = re.compile(r'^\s*(W/)?\s*"([^"]+)"\s*$')


def format_etag(version: int) -> str:
    """Return a weak ETag ``W/"<version>"`` from an integer row version."""
    return f'W/"{version}"'


def parse_etag(header: str) -> int:
    """Parse a weak or strong ETag header into an integer version.

    Raises:
        ValidationError: Header is missing or not an integer ETag.
    """
    match = _ETAG_RE.match(header)
    if match is None:
        msg = "If-Match must be a quoted ETag"
        raise ValidationError(msg, code=ErrorCode.VALIDATION_ERROR, context={"if_match": header})
    raw = match.group(2)
    try:
        return int(raw)
    except ValueError as exc:
        msg = "ETag version must be an integer"
        raise ValidationError(msg, code=ErrorCode.VALIDATION_ERROR) from exc


def etag_matches(if_match: str, version: int) -> bool:
    """Return whether ``If-Match`` equals the current row version (``*`` matches any)."""
    if if_match.strip() == "*":
        return True
    return parse_etag(if_match) == version


def assert_if_match(if_match: str | None, version: int) -> None:
    """Require a matching ``If-Match`` for PATCH; raise ``PRECONDITION_FAILED`` otherwise.

    Raises:
        ValidationError: ``If-Match`` missing (412) or stale (412).
    """
    if if_match is None or not if_match.strip():
        msg = "If-Match header is required for PATCH"
        raise ValidationError(msg, code=ErrorCode.PRECONDITION_FAILED)
    if not etag_matches(if_match, version):
        msg = f"If-Match does not match current version {version}"
        raise ValidationError(
            msg,
            code=ErrorCode.PRECONDITION_FAILED,
            context={"expected": format_etag(version)},
        )
