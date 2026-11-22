"""Filtered keyset run queries (T-081d, FR-API-001)."""

from __future__ import annotations

import base64
import json
import math
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from roboprobe.core.errors import ValidationError
from roboprobe.store.mapping import run_record
from roboprobe.store.orm import RunRow
from roboprobe.store.pagination import Page
from roboprobe.store.records import RunRecord

RunSort = Literal["ordinal", "-ordinal", "finished_at", "-finished_at", "robustness", "-robustness"]
__all__ = ["RunSort", "query_runs"]


def query_runs(  # noqa: PLR0913 - explicit documented filters
    session: Session,
    campaign_id: UUID,
    *,
    limit: int,
    cursor: str | None,
    sort: RunSort = "ordinal",
    status: str | None = None,
    verdict: str | None = None,
    phase: str | None = None,
    failure_class: str | None = None,
    tags: tuple[str, ...] = (),
) -> Page[RunRecord]:
    """Apply filters before stable keyset pagination; null sort values are ordered first."""
    name = sort.lstrip("-")
    field = getattr(RunRow, name)
    floor = datetime.min.replace(tzinfo=UTC) if name == "finished_at" else float("-inf")
    key = func.coalesce(field, floor) if name != "ordinal" else field
    query = select(RunRow).where(RunRow.campaign_id == campaign_id)
    for column, filter_value in (
        (RunRow.status, status),
        (RunRow.verdict, verdict),
        (RunRow.phase, phase),
        (RunRow.primary_failure, failure_class),
    ):
        if filter_value is not None:
            query = query.where(column == filter_value)
    if tags:
        query = query.where(RunRow.tags.contains(list(tags)))
    descending = sort.startswith("-")
    if cursor:
        value, last_id = _decode_position(cursor, sort)
        keys = tuple_(key, RunRow.id)
        boundary = tuple_(value, last_id)
        query = query.where(keys < boundary if descending else keys > boundary)
    query = (
        query.order_by(key.desc(), RunRow.id.desc())
        if descending
        else query.order_by(key, RunRow.id)
    )
    rows = session.scalars(query.limit(limit + 1)).all()
    records = [run_record(row) for row in rows[:limit]]
    next_cursor = None
    if len(rows) > limit and records:
        last = records[-1]
        next_value = getattr(last, name)
        if isinstance(next_value, datetime):
            next_value = next_value.isoformat()
        next_cursor = base64.urlsafe_b64encode(
            json.dumps(
                {
                    "sort": sort,
                    "value": next_value,
                    "id": str(last.id),
                }
            ).encode()
        ).decode()
    return Page(items=tuple(records), next_cursor=next_cursor)


def _decode_position(cursor: str, sort: RunSort) -> tuple[datetime | int | float, UUID]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor))
        if payload["sort"] != sort:
            raise ValueError  # noqa: TRY301 - rejected cursor boundary
        if not isinstance(payload["id"], str):
            raise TypeError  # noqa: TRY301
        return _cursor_value(sort.lstrip("-"), payload["value"]), UUID(payload["id"])
    except (ValueError, KeyError, TypeError) as exc:
        msg = "invalid run cursor"
        raise ValidationError(msg) from exc


def _cursor_value(name: str, value: object) -> datetime | int | float:
    if name == "finished_at":
        if value is None:
            return datetime.min.replace(tzinfo=UTC)
        if not isinstance(value, str):
            raise TypeError
        at = datetime.fromisoformat(value)
        if at.tzinfo is None:
            raise ValueError
        return at
    if name == "ordinal":
        if type(value) is not int:
            raise TypeError
        if not 0 <= value < 2**31:
            raise ValueError
        return value
    if value is None:
        return float("-inf")
    if not isinstance(value, (float, int)) or isinstance(value, bool):
        raise TypeError
    if not math.isfinite(value):
        raise ValueError
    return value
