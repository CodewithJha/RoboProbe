"""Campaign repository."""

# ruff: noqa: D102, D107

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from roboprobe.core.errors import ErrorCode, NotFoundError, ValidationError
from roboprobe.core.types import CampaignStatus
from roboprobe.store.flush import execute
from roboprobe.store.mapping import campaign_record
from roboprobe.store.orm import CampaignRow
from roboprobe.store.pagination import Page, clamp_limit, extra_item
from roboprobe.store.records import CampaignRecord


class SqlCampaignRepo:
    """Implements: CampaignRepo."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, campaign_id: UUID) -> CampaignRecord | None:
        row = self._s.get(CampaignRow, campaign_id)
        return None if row is None else campaign_record(row)

    def add(self, record: CampaignRecord) -> None:
        self._s.add(
            CampaignRow(
                id=record.id,
                name=record.name,
                space_id=record.space_id,
                space_version=record.space_version,
                sut_profile_id=record.sut_profile_id,
                backend=record.backend,
                strategy_id=record.strategy_id,
                strategy_params=dict(record.strategy_params),
                seed=record.seed,
                budget=record.budget,
                repeats=record.repeats,
                batch_size=record.batch_size,
                pins=dict(record.pins),
                oracle_config=dict(record.oracle_config),
                stop_rules=dict(record.stop_rules),
                status=record.status.value,
                status_reason=record.status_reason,
                experiment_id=record.experiment_id,
                experiment_rep=record.experiment_rep,
                tags=list(record.tags),
            )
        )
        self._s.flush()

    def set_status(
        self, campaign_id: UUID, status: CampaignStatus, *, reason: str | None = None
    ) -> None:
        result = execute(
            self._s,
            update(CampaignRow)
            .where(CampaignRow.id == campaign_id)
            .values(status=status.value, status_reason=reason),
        )
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            msg = "campaign not found"
            raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})

    def list(self, *, limit: int | None = None, cursor: str | None = None) -> Page[CampaignRecord]:
        size = clamp_limit(limit)
        stmt = select(CampaignRow).order_by(CampaignRow.id)
        if cursor is not None:
            stmt = stmt.where(CampaignRow.id > UUID(cursor))
        rows = self._s.scalars(stmt.limit(size + 1)).all()
        items, extra = extra_item([campaign_record(r) for r in rows], size)
        nxt = None if extra is None else str(items[-1].id)
        return Page(items=items, next_cursor=nxt)

    def list_for_experiment(self, experiment_id: UUID) -> tuple[CampaignRecord, ...]:
        rows = self._s.scalars(
            select(CampaignRow)
            .where(CampaignRow.experiment_id == experiment_id)
            .order_by(CampaignRow.id)
        ).all()
        return tuple(campaign_record(row) for row in rows)

    def etag_version(self, campaign_id: UUID) -> int:
        row = self._s.get(CampaignRow, campaign_id)
        if row is None:
            msg = "campaign not found"
            raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
        return int(row.etag_version)

    def patch(
        self,
        campaign_id: UUID,
        *,
        name: str | None = None,
        tags: Sequence[str] | None = None,
        expected_etag: int,
    ) -> int:
        row = self._s.get(CampaignRow, campaign_id)
        if row is None:
            msg = "campaign not found"
            raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
        if int(row.etag_version) != expected_etag:
            msg = "If-Match does not match current campaign version"
            raise ValidationError(
                msg,
                code=ErrorCode.PRECONDITION_FAILED,
                context={"campaign_id": str(campaign_id), "etag_version": int(row.etag_version)},
            )
        new_etag = int(row.etag_version) + 1
        values: dict[str, object] = {"etag_version": new_etag}
        if name is not None:
            values["name"] = name
        if tags is not None:
            values["tags"] = list(tags)
        result = execute(
            self._s,
            update(CampaignRow)
            .where(CampaignRow.id == campaign_id, CampaignRow.etag_version == expected_etag)
            .values(**values),
        )
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            msg = "campaign changed concurrently"
            raise ValidationError(msg, code=ErrorCode.PRECONDITION_FAILED)
        return new_etag

    def delete(self, campaign_id: UUID) -> None:
        result = execute(self._s, delete(CampaignRow).where(CampaignRow.id == campaign_id))
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            msg = "campaign not found"
            raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
