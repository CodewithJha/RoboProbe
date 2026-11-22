"""Filtered stable campaign pages (T-081b, FR-API-001)."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from roboprobe.core.errors import ValidationError
from roboprobe.store.mapping import campaign_record
from roboprobe.store.orm import CampaignRow
from roboprobe.store.pagination import Page
from roboprobe.store.records import CampaignRecord

__all__ = ["campaign_cursor", "decode_campaign_cursor", "query_campaigns"]


def campaign_cursor(record: CampaignRecord) -> str:
    """Encode the descending creation-time/id tie-breaker."""
    return base64.urlsafe_b64encode(
        json.dumps(
            {
                "created_at": None if record.created_at is None else record.created_at.isoformat(),
                "id": str(record.id),
            }
        ).encode()
    ).decode()


def decode_campaign_cursor(cursor: str) -> tuple[datetime, UUID]:
    """Validate an opaque keyset position."""
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor))
        if not isinstance(value["id"], str):
            raise TypeError  # noqa: TRY301 - cursor validation boundary
        created = value["created_at"]
        at = (
            datetime.min.replace(tzinfo=UTC) if created is None else datetime.fromisoformat(created)
        )
        if at.tzinfo is None:
            raise ValueError  # noqa: TRY301 - validation boundary
        return at, UUID(value["id"])
    except (ValueError, KeyError, TypeError) as exc:
        msg = "invalid campaign cursor"
        raise ValidationError(msg) from exc


def query_campaigns(  # noqa: PLR0913 - public filters
    session: Session,
    *,
    limit: int,
    cursor: str | None = None,
    status: str | None = None,
    strategy: str | None = None,
    backend: str | None = None,
) -> Page[CampaignRecord]:
    """Filter before paging, newest first; ids make equal timestamps stable."""
    created = func.coalesce(CampaignRow.created_at, datetime.min.replace(tzinfo=UTC))
    query = select(CampaignRow)
    for column, value in (
        (CampaignRow.status, status),
        (CampaignRow.strategy_id, strategy),
        (CampaignRow.backend, backend),
    ):
        if value is not None:
            query = query.where(column == value)
    if cursor is not None:
        at, last_id = decode_campaign_cursor(cursor)
        query = query.where(tuple_(created, CampaignRow.id) < tuple_(at, last_id))
    rows = session.scalars(
        query.order_by(created.desc(), CampaignRow.id.desc()).limit(limit + 1)
    ).all()
    records = tuple(campaign_record(row) for row in rows[:limit])
    return Page(
        items=records, next_cursor=campaign_cursor(records[-1]) if len(rows) > limit else None
    )
