"""Report generation jobs for HTTP and CLI (docs/12 §2).

Implements: T-084
"""

# ruff: noqa: D102, D107, ANN401, PLC0415

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID

from roboprobe.core.errors import NotFoundError

__all__ = ["ReportJob", "ReportJobStore"]

_Kind = Literal["campaign", "experiment"]


@dataclass(slots=True)
class ReportJob:
    """One HTML report generation job."""

    id: UUID
    kind: _Kind
    target_id: UUID
    status: str
    html_path: Path | None = None


class ReportJobStore:
    """In-process report jobs."""

    def __init__(self, executor: ThreadPoolExecutor) -> None:
        self._executor = executor
        self._jobs: dict[UUID, ReportJob] = {}
        self._lock = threading.Lock()

    def submit(self, kind: _Kind, target_id: UUID, work: Any) -> ReportJob:
        job = ReportJob(id=uuid.uuid4(), kind=kind, target_id=target_id, status="RUNNING")
        with self._lock:
            self._jobs[job.id] = job
        self._executor.submit(self._run, job.id, work)
        return job

    def get(self, job_id: UUID) -> ReportJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _run(self, job_id: UUID, work: Any) -> None:
        try:
            path = cast("Path", work())
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job.status = "COMPLETED"
                    job.html_path = path
        except Exception:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job.status = "FAILED"


def build_report_work(
    kind: _Kind,
    target_id: UUID,
    *,
    uow_factory: Any,
    artifact_store: Any,
    settings: Any,
) -> Any:
    """Return a callable that renders HTML to a path."""

    def _work() -> Path:
        from roboprobe.reporting.campaign import render_campaign_report
        from roboprobe.reporting.experiment import render_experiment_report
        from roboprobe.reporting.ports import ReportArtifactStore, ReportUnitOfWork

        with uow_factory() as uow:
            if kind == "campaign" and uow.campaigns.get(target_id) is None:
                msg = "campaign not found"
                raise NotFoundError(msg, context={"campaign_id": str(target_id)})
            if kind == "experiment" and uow.experiments.get(target_id) is None:
                msg = "experiment not found"
                raise NotFoundError(msg, context={"experiment_id": str(target_id)})
            if kind == "campaign":
                return render_campaign_report(
                    target_id,
                    cast(ReportUnitOfWork, uow),
                    cast(ReportArtifactStore, artifact_store),
                    settings=settings.reporting,
                )
            return render_experiment_report(
                target_id,
                cast(ReportUnitOfWork, uow),
                cast(ReportArtifactStore, artifact_store),
                settings=settings.reporting,
                experiment_settings=settings.experiments,
            )

    return _work
