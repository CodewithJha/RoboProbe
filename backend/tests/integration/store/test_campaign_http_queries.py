"""Campaign list stays bounded at 10k runs (T-081b/d, NFR-PERF-004)."""

from __future__ import annotations

from collections.abc import Callable
from statistics import quantiles
from time import perf_counter
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Connection
from tests.integration.store._seed import seed_campaign

from roboprobe.api.app import create_app
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.store.records import NewRun
from roboprobe.store.uow import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.integration
_RUNS = 10_000
_BATCH = 250
_REQUESTS = 20
_P95_TARGET_S = 0.2  # NFR-PERF-004 / issue #149 acceptance threshold.


def test_campaign_list_10k_runs_uses_three_queries_and_meets_latency(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
    pg_connection: Connection,
) -> None:
    with uow_factory() as uow:
        cid, _ = seed_campaign(uow, budget=_RUNS)
        for start in range(0, _RUNS, _BATCH):
            uow.runs.insert_batch(
                [
                    NewRun(
                        campaign_id=cid,
                        ordinal=ordinal,
                        backend="kinematic2d",
                        scenario_hash=f"h{ordinal}",
                        scenario_values={},
                        x_unit=(),
                        seed=ordinal,
                        phase="manual",
                    )
                    for ordinal in range(start, start + _BATCH)
                ]
            )
        uow.commit()
    settings = RoboProbeSettings(observability={"metrics_enabled": False})
    app = create_app(settings)
    app.state.event_hub_autostart = False
    app.state.services = SimpleNamespace(
        settings=settings, uow_factory=uow_factory, close=lambda: None
    )
    queries = []

    def capture(_connection, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    with TestClient(app) as client:
        assert client.get("/api/v1/campaigns").status_code == 200
        event.listen(pg_connection, "before_cursor_execute", capture)
        try:
            timings = []
            run_timings = []
            for _ in range(_REQUESTS):
                queries.clear()
                start = perf_counter()
                response = client.get(
                    "/api/v1/campaigns", params={"status": "RUNNING", "backend": "kinematic2d"}
                )
                timings.append(perf_counter() - start)
                assert response.status_code == 200
                assert response.json()["items"][0]["counts"]["pending"] == _RUNS
                assert len(queries) <= 3
                queries.clear()
                start = perf_counter()
                runs = client.get(
                    f"/api/v1/campaigns/{cid}/runs",
                    params={"status": "PENDING", "phase": "manual", "sort": "ordinal"},
                )
                run_timings.append(perf_counter() - start)
                assert runs.status_code == 200
                assert len(runs.json()["items"]) == settings.api.page_limit_default
                assert all(item["phase"] == "manual" for item in runs.json()["items"])
                assert len(queries) <= 2
            assert quantiles(timings, n=20)[18] < _P95_TARGET_S
            assert quantiles(run_timings, n=20)[18] < _P95_TARGET_S
        finally:
            event.remove(pg_connection, "before_cursor_execute", capture)
