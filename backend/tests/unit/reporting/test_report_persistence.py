"""Report jobs survive restart and unfinished work fails safely (T-084a)."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from roboprobe.bootstrap.report_jobs import SqlReportJobs
from roboprobe.reporting.report_jobs import ReportJob, ReportJobStore
from roboprobe.store.orm import ReportJobRow

pytestmark = pytest.mark.unit


def test_completed_job_survives_new_store_and_running_job_is_failed(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    ReportJobRow.__table__.create(engine)
    persistence = SqlReportJobs(sessionmaker(engine))
    completed = ReportJob(uuid4(), "campaign", uuid4(), "COMPLETED", tmp_path / "report.html")
    interrupted = ReportJob(uuid4(), "experiment", uuid4(), "RUNNING")
    persistence.save(completed)
    persistence.save(interrupted)
    with ThreadPoolExecutor(max_workers=1) as pool:
        store = ReportJobStore(pool, persistence)
        assert store.get(completed.id).html_path == completed.html_path
        assert store.get(interrupted.id).status == "FAILED"
    engine.dispose()


def test_job_completion_and_failure_are_persisted(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'execution.db'}")
    ReportJobRow.__table__.create(engine)
    persistence = SqlReportJobs(sessionmaker(engine))

    def fail() -> Path:
        raise RuntimeError

    with ThreadPoolExecutor(max_workers=1) as pool:
        store = ReportJobStore(pool, persistence)
        completed = store.submit("campaign", uuid4(), lambda: tmp_path / "result.html")
        failed = store.submit("campaign", uuid4(), fail)
    assert persistence.get(completed.id).status == "COMPLETED"
    assert persistence.get(failed.id).status == "FAILED"
    assert persistence.get(uuid4()) is None
    engine.dispose()
