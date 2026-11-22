"""Extra unit coverage for M7 API helpers."""

# ruff: noqa: RUF012, PLW0108, B017

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from roboprobe.api.mapping import (
    artifact_out,
    campaign_counts,
    campaign_out,
    experiment_out,
    failure_mode_out,
    risk_out,
    run_out,
    space_out,
    sut_out,
    worker_out,
)
from roboprobe.core.types import CampaignStatus, RunStatus, Verdict
from roboprobe.reporting.report_jobs import ReportJobStore, build_report_work
from roboprobe.scenario.repo_root import discover_repo_root

pytestmark = pytest.mark.unit


class _Run:
    status = RunStatus.DONE
    verdict = Verdict.FAIL
    id = uuid4()
    campaign_id = uuid4()
    ordinal = 1
    repeat_index = 0
    scenario_hash = "ab"
    scenario_values = {"x": 1.0}
    proposal = {}
    seed = 1
    robustness = -0.1
    primary_failure = "F-COL"
    warnings = ()
    metrics = {}
    worker_id = None
    enqueued_at = None
    started_at = None
    finished_at = None
    phase = "mode_search"
    tags = ()


def test_mapping_helpers() -> None:
    cid = uuid4()
    out = campaign_out(
        type(
            "C",
            (),
            {
                "id": cid,
                "name": "n",
                "status": CampaignStatus.CREATED,
                "backend": "kinematic2d",
                "strategy_id": "S-RANDOM",
                "strategy_params": {},
                "seed": 1,
                "budget": 10,
                "repeats": 1,
                "batch_size": 1,
                "tags": (),
                "created_at": None,
                "started_at": None,
                "finished_at": None,
            },
        )(),
        base_path="/api/v1",
        counts={"done": 1},
    )
    assert out.links["self"].endswith(str(cid))
    counts = campaign_counts([_Run(), _Run()], budget=10)
    assert counts["fail"] == 2
    run = run_out(_Run(), oracles=[{"oracle_id": "O-CLEAR", "violated": True}])
    assert run.verdict == "FAIL"
    assert (
        space_out(
            type(
                "S",
                (),
                {"id": "s", "version": "v", "name": "n", "schema_version": 1, "created_at": None},
            )()
        ).id
        == "s"
    )
    assert (
        sut_out(
            type(
                "P",
                (),
                {"id": "p", "backend": "b", "config_hash": "h", "created_at": None},
            )()
        ).config_hash
        == "h"
    )
    mid = uuid4()
    assert (
        failure_mode_out(
            type(
                "M",
                (),
                {
                    "id": mid,
                    "campaign_id": cid,
                    "code": "FM-01",
                    "label": "l",
                    "size": 2,
                    "primary_class": "F-COL",
                    "status": "open",
                    "interaction": None,
                },
            )()
        ).code
        == "FM-01"
    )
    assert (
        risk_out(
            type(
                "R",
                (),
                {"robustness_score": 0.5, "volumes": {}, "thresholds": {}},
            )(),
            campaign_id=cid,
        ).robustness_score
        == 0.5
    )
    assert (
        experiment_out(
            type(
                "E",
                (),
                {
                    "id": cid,
                    "name": "e",
                    "status": "CREATED",
                    "design": {},
                    "results": None,
                    "created_at": None,
                    "finished_at": None,
                },
            )()
        ).name
        == "e"
    )
    assert (
        artifact_out(
            type(
                "A",
                (),
                {
                    "id": uuid4(),
                    "kind": "trace",
                    "sha256": "a" * 64,
                    "size_bytes": 1,
                    "media_type": "application/octet-stream",
                },
            )()
        ).kind
        == "trace"
    )
    assert worker_out(
        type(
            "W",
            (),
            {
                "id": "w",
                "backend": "kinematic2d",
                "status": "IDLE",
                "version": "1",
                "last_heartbeat": datetime.now(tz=UTC),
                "current_run_id": None,
            },
        )(),
        now=datetime.now(tz=UTC),
    ).id.startswith("worker-")


def test_report_job_store() -> None:
    store = ReportJobStore(ThreadPoolExecutor(max_workers=1))
    job = store.submit("campaign", uuid4(), lambda: Path(__file__))
    assert store.get(job.id) is not None


def test_build_report_work_raises(tmp_path: Path) -> None:
    class _Uow:
        def __enter__(self) -> _Uow:
            return self

        def __exit__(self, *a: object) -> None:
            return None

        campaigns = type("C", (), {"get": lambda *_: None})()
        experiments = type("E", (), {"get": lambda *_: None})()

    work = build_report_work(
        "campaign",
        uuid4(),
        uow_factory=lambda: _Uow(),
        artifact_store=object(),
        settings=type("S", (), {"reporting": object(), "experiments": object()})(),
    )
    with pytest.raises(Exception):
        work()


def test_discover_repo_root() -> None:
    root = discover_repo_root()
    assert (root / "configs" / "scenario_spaces").is_dir() or root.is_dir()


def test_workers_route(api_client: TestClient) -> None:
    class _Page:
        items: list[object] = []
        next_cursor = None

    class _Workers:
        def list(self, **_kwargs: object) -> _Page:
            return _Page()

    class _Uow:
        workers = _Workers()

        def commit(self) -> None:
            return None

        def close(self) -> None:
            return None

    api_client.app.state.services.uow_factory = _Uow
    assert api_client.get("/api/v1/workers").status_code == 200
