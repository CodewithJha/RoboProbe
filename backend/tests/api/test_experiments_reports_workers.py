"""Compare the experiment API and rendered report from one recorded snapshot."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from roboprobe.core.types import CampaignStatus, Verdict
from roboprobe.reporting.report_jobs import ReportJobStore
from roboprobe.store.pagination import Page

pytestmark = pytest.mark.unit
_EXPERIMENT = UUID(int=100)
_CAMPAIGN = UUID(int=200)
_DESIGN = {
    "schema_version": 1,
    "id": "report-parity",
    "backend": "kinematic2d",
    "space": {"id": "warehouse_v1"},
    "budget": 3,
    "seeds": {"root": 42, "count": 1},
    "strategies": [{"id": "S-RANDOM"}],
    "metrics": ["MET-01", "MET-03"],
}


def _run(identifier: int, ordinal: int, verdict: Verdict) -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID(int=identifier),
        ordinal=ordinal,
        repeat_index=0,
        verdict=verdict,
        metrics={},
        x_unit=(),
        phase=None,
        tags=(),
    )


class _ComparisonUow:
    def __init__(self, *, stored: bool) -> None:
        results = (
            {
                "experiment_id": str(_EXPERIMENT),
                "metrics": ["MET-01", "MET-03"],
                "strategies": {
                    "S-RANDOM": {
                        "MET-01": {"median": 0.75, "ci95": [0.5, 0.9], "iqr": [0.7, 0.8]},
                        "MET-03": {"median": 3, "ci95": [1, 3], "iqr": [2, 3]},
                    },
                },
                "tests": [],
            }
            if stored
            else None
        )
        self.experiments = SimpleNamespace(
            get=lambda _: SimpleNamespace(name="Parity <sample>", design=_DESIGN, results=results)
        )
        self.campaigns = SimpleNamespace(
            list_for_experiment=lambda _: (
                SimpleNamespace(
                    id=_CAMPAIGN,
                    strategy_id="S-RANDOM",
                    status=CampaignStatus.COMPLETED,
                    budget=3,
                    experiment_rep=1,
                    tags=(),
                ),
            )
        )
        self.runs = SimpleNamespace(list_for_campaign=self._page)

    @staticmethod
    def _page(
        campaign_id: UUID, *, limit: int | None = None, cursor: str | None = None
    ) -> Page[SimpleNamespace]:
        assert campaign_id == _CAMPAIGN
        assert limit is None
        if cursor is None:
            return Page(items=(_run(1, 3, Verdict.PASS),), next_cursor="more")
        assert cursor == "more"
        return Page(items=(_run(2, 1, Verdict.PASS), _run(3, 2, Verdict.FAIL)))

    def __enter__(self) -> _ComparisonUow:
        return self

    def __exit__(self, *_: object) -> None:
        return None


@pytest.mark.parametrize("stored", [False, True], ids=["paginated", "persisted"])
def test_report_embeds_the_comparison_api_result(
    api_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, stored: bool
) -> None:
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    services = api_client.app.state.services
    services.uow_factory = lambda: _ComparisonUow(stored=stored)
    services.artifact_store = Mock()
    with ThreadPoolExecutor(max_workers=1) as pool:
        services.report_jobs = ReportJobStore(pool)
        comparison = api_client.get(f"/api/v1/experiments/{_EXPERIMENT}/comparison")
        assert comparison.status_code == HTTPStatus.OK
        body = comparison.json()
        started = api_client.post(
            "/api/v1/reports", json={"kind": "experiment", "id": str(_EXPERIMENT)}
        )
        assert started.status_code == HTTPStatus.ACCEPTED
        job_id = started.json()["id"]

    status = api_client.get(f"/api/v1/reports/{job_id}")
    assert status.json()["status"] == "COMPLETED"
    content = api_client.get(f"/api/v1/reports/{job_id}/content")
    assert content.status_code == HTTPStatus.OK
    _, opening, tail = content.text.partition(
        '<script type="application/json" id="experiment-comparison">'
    )
    assert opening, "the offline report must include the exact API comparison JSON"
    assert json.loads(tail.split("</script>", 1)[0]) == body
    stats = body["strategies"]["S-RANDOM"]
    assert stats["MET-01"]["median"] == pytest.approx(0.75 if stored else 1 / 3)
    assert stats["MET-03"]["median"] == (3 if stored else 2)
