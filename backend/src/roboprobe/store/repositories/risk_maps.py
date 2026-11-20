"""Risk-map repository."""

# ruff: noqa: D102, D107

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from roboprobe.store.mapping import risk_record
from roboprobe.store.orm import RiskMapRow
from roboprobe.store.records import RiskMapRecord


class SqlRiskMapRepo:
    """Implements: RiskMapRepo."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, record: RiskMapRecord) -> None:
        self._s.add(
            RiskMapRow(
                id=record.id,
                campaign_id=record.campaign_id,
                analysis_id=record.analysis_id,
                n_obs=record.n_obs,
                thresholds=dict(record.thresholds),
                volumes=dict(record.volumes),
                robustness_score=record.robustness_score,
                slices_artifact=record.slices_artifact,
            )
        )
        self._s.flush()

    def latest(self, campaign_id: UUID) -> RiskMapRecord | None:
        row = self._s.scalars(
            select(RiskMapRow)
            .where(RiskMapRow.campaign_id == campaign_id)
            .order_by(RiskMapRow.created_at.desc())
            .limit(1)
        ).first()
        return None if row is None else risk_record(row)
