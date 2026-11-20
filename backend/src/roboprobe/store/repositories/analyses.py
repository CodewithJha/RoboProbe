"""Analysis repository."""

# ruff: noqa: D102, D107

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from roboprobe.store.mapping import analysis_record
from roboprobe.store.orm import AnalysisRow
from roboprobe.store.records import AnalysisRecord


class SqlAnalysisRepo:
    """Implements: AnalysisRepo."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, analysis_id: UUID) -> AnalysisRecord | None:
        row = self._s.get(AnalysisRow, analysis_id)
        return None if row is None else analysis_record(row)

    def add(self, record: AnalysisRecord) -> None:
        self._s.add(
            AnalysisRow(
                id=record.id,
                campaign_id=record.campaign_id,
                kind=record.kind,
                status=record.status,
                n_runs=record.n_runs,
                summary=None if record.summary is None else dict(record.summary),
                report_sha256=record.report_sha256,
                analysis_schema_version=record.analysis_schema_version,
            )
        )

    def list_for_campaign(self, campaign_id: UUID) -> tuple[AnalysisRecord, ...]:
        rows = self._s.scalars(
            select(AnalysisRow)
            .where(AnalysisRow.campaign_id == campaign_id)
            .order_by(AnalysisRow.created_at)
        ).all()
        return tuple(analysis_record(r) for r in rows)
