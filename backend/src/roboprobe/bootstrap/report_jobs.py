"""Persistent report job adapter (T-084a, FR-API-001)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from roboprobe.reporting.report_jobs import ReportJob
from roboprobe.store.orm import ReportJobRow

__all__ = ["SqlReportJobs"]


class SqlReportJobs:
    """Store report status and output paths across API restarts."""

    def __init__(self, factory: Callable[[], Session]) -> None:
        """Inject an independent session factory."""
        self._factory = factory

    def save(self, job: ReportJob) -> None:
        """Persist the latest job state atomically."""
        with self._factory() as session:
            session.merge(
                ReportJobRow(
                    id=job.id,
                    kind=job.kind,
                    target_id=job.target_id,
                    status=job.status,
                    html_path=None if job.html_path is None else str(job.html_path),
                )
            )
            session.commit()

    def get(self, job_id: UUID) -> ReportJob | None:
        """Load a job, including jobs submitted before restart."""
        with self._factory() as session:
            row = session.get(ReportJobRow, job_id)
            if row is None:
                return None
            return ReportJob(
                id=row.id,
                kind=cast('Literal["campaign", "experiment", "bundle"]', row.kind),
                target_id=row.target_id,
                status=row.status,
                html_path=None if row.html_path is None else Path(row.html_path),
            )

    def recover(self) -> None:
        """Mark work interrupted by the prior API process as failed."""
        with self._factory() as session:
            session.execute(
                update(ReportJobRow).where(ReportJobRow.status == "RUNNING").values(status="ERROR")
            )
            session.commit()
