"""Filtered keyset run queries (T-081d, FR-API-001)."""

from __future__ import annotations

import base64
import json
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
        try:
            payload = json.loads(base64.urlsafe_b64decode(cursor))
            if payload["sort"] != sort:
                raise ValueError  # noqa: TRY301 - rejected with the other cursor failures
            value = payload["value"]
            if name == "finished_at" and value is not None:
                value = datetime.fromisoformat(value)
            if value is None:
                value = floor
            boundary = tuple_(value, UUID(payload["id"]))
        except (ValueError, KeyError, TypeError) as exc:
            msg = "invalid run cursor"
            raise ValidationError(msg) from exc
        keys = tuple_(key, RunRow.id)
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
        value = getattr(last, name)
        if isinstance(value, datetime):
            value = value.isoformat()
        next_cursor = base64.urlsafe_b64encode(
            json.dumps(
                {
                    "sort": sort,
                    "value": value,
                    "id": str(last.id),
                }
            ).encode()
        ).decode()
    return Page(items=tuple(records), next_cursor=next_cursor)
