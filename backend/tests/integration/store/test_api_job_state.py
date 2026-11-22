"""PostgreSQL persistence for report recovery and experiment notes (T-084a)."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from roboprobe.bootstrap.report_jobs import SqlReportJobs
from roboprobe.reporting.report_jobs import ReportJob, ReportJobStore

pytestmark = pytest.mark.integration


def test_jobs_survive_api_process_replacement(pg_engine: Engine, tmp_path: Path) -> None:
    target = uuid4()
    completed = ReportJob(uuid4(), "campaign", target, "COMPLETED", tmp_path / "report.html")
    interrupted = ReportJob(uuid4(), "experiment", target, "RUNNING")
    previous_process = SqlReportJobs(sessionmaker(pg_engine))
    previous_process.save(completed)
    previous_process.save(interrupted)

    with ThreadPoolExecutor(max_workers=1) as executor:
        replacement = ReportJobStore(executor, SqlReportJobs(sessionmaker(pg_engine)))
        assert replacement.get(completed.id) == completed
        recovered = replacement.get(interrupted.id)
        assert recovered is not None and recovered.status == "ERROR"
    assert previous_process.get(interrupted.id) == recovered
