"""Artifact metadata repository."""

# ruff: noqa: D102, D107

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from roboprobe.store.mapping import artifact_record
from roboprobe.store.orm import ArtifactRow
from roboprobe.store.records import ArtifactRecord


class SqlArtifactRepo:
    """Implements: ArtifactRepo."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, record: ArtifactRecord) -> None:
        self._s.add(
            ArtifactRow(
                id=record.id,
                run_id=record.run_id,
                campaign_id=record.campaign_id,
                kind=record.kind,
                sha256=record.sha256,
                size_bytes=record.size_bytes,
                rel_path=record.rel_path,
                media_type=record.media_type,
            )
        )

    def get(self, artifact_id: UUID) -> ArtifactRecord | None:
        row = self._s.get(ArtifactRow, artifact_id)
        return None if row is None else artifact_record(row)

    def list_for_run(self, run_id: UUID) -> tuple[ArtifactRecord, ...]:
        rows = self._s.scalars(
            select(ArtifactRow).where(ArtifactRow.run_id == run_id).order_by(ArtifactRow.created_at)
        ).all()
        return tuple(artifact_record(r) for r in rows)

    def sha256_set(self) -> frozenset[str]:
        rows = self._s.scalars(select(ArtifactRow.sha256)).all()
        return frozenset(rows)

    def delete(self, artifact_id: UUID) -> None:
        self._s.execute(delete(ArtifactRow).where(ArtifactRow.id == artifact_id))

    def bags_for_retention(self) -> tuple[ArtifactRecord, ...]:
        rows = self._s.scalars(select(ArtifactRow).where(ArtifactRow.kind == "bag")).all()
        return tuple(artifact_record(r) for r in rows)
