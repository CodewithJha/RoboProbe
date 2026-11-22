"""M7 API surface smoke tests (T-081, T-082, T-084)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tests.api.test_campaigns_crud import client as client  # noqa: PLC0414 - shared fixture

from roboprobe.core.types import CampaignStatus
from roboprobe.store.records import ExperimentRecord, WorkerRecord

pytestmark = pytest.mark.unit

_CID = uuid4()


@dataclass
class _Campaign:
    id: UUID
    name: str
    status: CampaignStatus
    backend: str
    strategy_id: str
    strategy_params: dict[str, object]
    seed: int
    budget: int
    repeats: int
    batch_size: int
    tags: tuple[str, ...]
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    space_id: str = "warehouse_v1"
    space_version: str = "a"
    sut_profile_id: str = "k2d_default"
    pins: dict[str, object] = None  # type: ignore[assignment]
    oracle_config: dict[str, object] = None  # type: ignore[assignment]
    stop_rules: dict[str, object] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.pins is None:
            self.pins = {}
        if self.oracle_config is None:
            self.oracle_config = {}
        if self.stop_rules is None:
            self.stop_rules = {}


class _Page:
    def __init__(self, items: list[Any], next_cursor: str | None = None) -> None:
        self.items = items
        self.next_cursor = next_cursor


class _Campaigns:
    def __init__(self) -> None:
        self._rows = {
            _CID: _Campaign(
                id=_CID,
                name="t",
                status=CampaignStatus.CREATED,
                backend="kinematic2d",
                strategy_id="S-RANDOM",
                strategy_params={},
                seed=1,
                budget=10,
                repeats=1,
                batch_size=1,
                tags=(),
            )
        }
        self._etag = 1

    def get(self, campaign_id: UUID) -> _Campaign | None:
        return self._rows.get(campaign_id)

    def list(self, *, limit: int | None = None, cursor: str | None = None) -> _Page:
        return _Page(list(self._rows.values()))

    def etag_version(self, campaign_id: UUID) -> int:
        return self._etag

    def patch(self, campaign_id: UUID, *, name, tags, expected_etag: int) -> int:
        self._etag += 1
        row = self._rows[campaign_id]
        if name is not None:
            row.name = name
        if tags is not None:
            row.tags = tuple(tags)
        return self._etag

    def delete(self, campaign_id: UUID) -> None:
        del self._rows[campaign_id]


class _Runs:
    def list_for_campaign(
        self, campaign_id: UUID, *, limit: int | None = None, cursor: str | None = None
    ) -> _Page:
        return _Page([])


class _Modes:
    def list_for_campaign(self, campaign_id: UUID) -> tuple[()]:
        return ()


class _Uow:
    def __init__(self) -> None:
        self.campaigns = _Campaigns()
        self.runs = _Runs()
        self.modes = _Modes()
        self.experiments = _Experiments()
        self.analyses = _Analyses()
        self.risk_maps = _Risk()
        self.spaces = _Spaces()
        self.workers = _Workers()

    def commit(self) -> None:
        return None

    def close(self) -> None:
        return None


class _Experiments:
    def list(self, **_: object) -> _Page:
        return _Page([])

    def get(self, _: UUID) -> None:
        return None


class _Analyses:
    def list_for_campaign(self, _: UUID) -> tuple[()]:
        return ()


class _Risk:
    def latest(self, _: UUID) -> None:
        return None


class _Spaces:
    def get(self, *_: object) -> None:
        return None

    def list(self, **_: object) -> _Page:
        return _Page([])


class _Workers:
    def list(self, **_: object) -> _Page:
        return _Page([])


class _CampaignSvc:
    def start(self, _: UUID) -> CampaignStatus:
        return CampaignStatus.RUNNING


@pytest.fixture
def m7_client(api_client: TestClient, api_settings, tmp_path: Path) -> Iterator[TestClient]:
    uow = _Uow()

    def factory() -> _Uow:
        return uow

    api_client.app.state.services.uow_factory = factory
    api_client.app.state.services.campaigns = _CampaignSvc()
    api_client.app.state.services.analysis = type("A", (), {"schedule": lambda *a, **k: None})()
    api_client.app.state.services.report_jobs = type(
        "R",
        (),
        {
            "get": lambda *a: None,
            "submit": lambda *a: type(
                "J", (), {"id": uuid4(), "status": "RUNNING", "kind": "campaign", "target_id": _CID}
            )(),
        },
    )()
    api_client.app.state.services.space_root = tmp_path
    yield api_client


def test_list_campaigns(m7_client: TestClient) -> None:
    resp = m7_client.get("/api/v1/campaigns")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1


def test_get_campaign_etag(m7_client: TestClient) -> None:
    resp = m7_client.get(f"/api/v1/campaigns/{_CID}")
    assert resp.status_code == 200
    assert "etag" in resp.headers.get("etag", "").lower() or resp.headers.get("ETag")


def test_campaign_start_accepted(m7_client: TestClient) -> None:
    resp = m7_client.post(f"/api/v1/campaigns/{_CID}:start")
    assert resp.status_code == 202


def test_experiments_list(m7_client: TestClient) -> None:
    resp = m7_client.get("/api/v1/experiments")
    assert resp.status_code == 200


def test_experiment_comparison_uses_saved_report_results(
    m7_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment_id = uuid4()
    results = {
        "experiment_id": str(experiment_id),
        "metrics": ["MET-01"],
        "strategies": {"S-RANDOM": {"MET-01": {"median": 0.4}}},
        "tests": [],
    }
    monkeypatch.setattr(_Experiments, "get", lambda *_: SimpleNamespace(results=results))
    response = m7_client.get(f"/api/v1/experiments/{experiment_id}/comparison")
    assert response.status_code == 200
    assert response.json() == results


def test_experiment_notes_require_current_etag(client: TestClient) -> None:
    experiment_id = uuid4()
    services = client.app.state.services
    with services.uow_factory() as uow:
        uow.experiments.add(
            ExperimentRecord(id=experiment_id, name="Trial", design={}, status="CREATED")
        )
        uow.commit()
    url = f"/api/v1/experiments/{experiment_id}"
    first = client.get(url)
    assert first.status_code == 200
    stale = first.headers["ETag"]
    saved = client.patch(url, headers={"If-Match": stale}, json={"notes": "Saved"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["notes"] == "Saved"
    assert saved.headers["ETag"] != stale
    rejected = client.patch(url, headers={"If-Match": stale}, json={"notes": "Stale"})
    assert rejected.status_code == 412
    assert client.get(url).json()["notes"] == "Saved"


def test_worker_list_redacts_hostname(client: TestClient) -> None:
    host = "private-lab-host"
    with client.app.state.services.uow_factory() as uow:
        uow.workers.register(
            WorkerRecord(
                id=f"{host}:1234:0",
                backend="kinematic2d",
                status="IDLE",
                capabilities={},
                version="1",
            )
        )
        uow.commit()
    response = client.get("/api/v1/workers")
    assert response.status_code == 200
    assert host not in response.text
    assert response.json()["items"][0]["id"].startswith("worker-")
