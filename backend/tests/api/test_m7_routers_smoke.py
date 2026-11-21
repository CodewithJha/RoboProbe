"""Smoke M7 routes with layered in-memory repos."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from roboprobe.core.types import CampaignStatus, Verdict
from roboprobe.reporting.report_jobs import ReportJobStore
from roboprobe.runner.lifecycle import CampaignService

pytestmark = pytest.mark.unit

_CID = uuid4()
_RID = uuid4()
_MID = uuid4()


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
    space_id: str = "warehouse_v1"
    space_version: str = "1"
    sut_profile_id: str = "k2d_default"
    pins: dict[str, object] = field(default_factory=dict)
    oracle_config: dict[str, object] = field(default_factory=dict)
    stop_rules: dict[str, object] = field(default_factory=dict)
    created_at: object = None
    started_at: object = None
    finished_at: object = None


class _Page:
    def __init__(self, items: list[Any], next_cursor: str | None = None) -> None:
        self.items = items
        self.next_cursor = next_cursor


class _Uow:
    def __init__(self) -> None:
        self.campaign = _Campaign(
            id=_CID,
            name="c",
            status=CampaignStatus.COMPLETED,
            backend="kinematic2d",
            strategy_id="S-RANDOM",
            strategy_params={},
            seed=1,
            budget=3,
            repeats=1,
            batch_size=1,
            tags=(),
        )
        self.campaigns = _Campaigns(self.campaign)
        self.runs = _Runs(self.campaign)
        self.modes = _Modes()
        self.analyses = _Analyses()
        self.risk_maps = _Risk()
        self.spaces = _Spaces()
        self.workers = _Workers()
        self.sut_profiles = _Sut()
        self.experiments = _Experiments()
        self.artifacts = _Artifacts()
        self.oracle_results = _Oracles()

    def commit(self) -> None:
        return None

    def close(self) -> None:
        return None


class _Campaigns:
    def __init__(self, row: _Campaign) -> None:
        self._row = row

    def get(self, cid: UUID) -> _Campaign | None:
        return self._row if cid == self._row.id else None

    def list(self, **_: object) -> _Page:
        return _Page([self._row])

    def etag_version(self, _: UUID) -> int:
        return 1

    def patch(self, *_: object, **__: object) -> int:
        return 2

    def delete(self, _: UUID) -> None:
        return None

    def list_for_experiment(self, _: UUID) -> tuple[_Campaign, ...]:
        return (self._row,)


class _Runs:
    def __init__(self, campaign: _Campaign) -> None:
        self._run = SimpleNamespace(
            id=_RID,
            campaign_id=campaign.id,
            ordinal=1,
            repeat_index=0,
            status="DONE",
            phase="mode_search",
            scenario_hash="h",
            scenario_values={"robot.max_speed": 0.2},
            proposal={},
            seed=1,
            verdict=Verdict.FAIL,
            robustness=-0.2,
            primary_failure="F-COL",
            warnings=(),
            metrics={},
            worker_id=None,
            enqueued_at=None,
            started_at=None,
            finished_at=None,
            tags=(),
            backend="kinematic2d",
            attempt=1,
            x_unit=(0.5,),
        )

    def get(self, rid: UUID) -> Any:
        return self._run if rid == _RID else None

    def list_for_campaign(self, *_: object, **__: object) -> _Page:
        return _Page([self._run])

    def insert_batch(self, _: object) -> tuple[UUID, ...]:
        return (uuid4(),)


class _Modes:
    def get(self, mid: UUID) -> Any:
        if mid != _MID:
            return None
        return SimpleNamespace(
            id=_MID,
            campaign_id=_CID,
            code="FM-01",
            label="l",
            size=1,
            primary_class="F-COL",
            status="open",
            interaction=None,
        )

    def list_for_campaign(self, _: UUID) -> tuple[Any, ...]:
        row = self.get(_MID)
        return (row,) if row else ()

    def patch(self, *_: object, **__: object) -> None:
        return None


class _Analyses:
    def list_for_campaign(self, _: UUID) -> tuple[Any, ...]:
        return (
            SimpleNamespace(
                id=uuid4(),
                campaign_id=_CID,
                kind="FULL",
                status="OK",
                summary={"importance": {}, "rules": []},
            ),
        )


class _Risk:
    def latest(self, _: UUID) -> Any:
        return SimpleNamespace(
            robustness_score=0.4,
            volumes={},
            thresholds={},
            slices_artifact=None,
        )


class _Spaces:
    def list(self, **_: object) -> _Page:
        return _Page([])

    def get(self, *_: object) -> Any:
        return None


class _Workers:
    def list(self, **_: object) -> _Page:
        return _Page([])


class _Sut:
    def list(self, **_: object) -> _Page:
        return _Page([])


class _Experiments:
    def list(self, **_: object) -> _Page:
        return _Page([])

    def get(self, _: UUID) -> None:
        return None


class _Artifacts:
    def get(self, _: UUID) -> None:
        return None

    def list_for_run(self, _: UUID) -> list[Any]:
        return []


class _Oracles:
    def list_for_run(self, _: UUID) -> tuple[Any, ...]:
        return ()


@pytest.fixture
def smoke_client(api_client: TestClient) -> Iterator[TestClient]:
    uow = _Uow()
    api_client.app.state.services.uow_factory = lambda: uow
    api_client.app.state.services.campaigns = CampaignService(lambda: uow)
    api_client.app.state.services.analysis = SimpleNamespace(schedule=lambda *a, **k: None)
    api_client.app.state.services.report_jobs = ReportJobStore(ThreadPoolExecutor(max_workers=1))
    yield api_client


def test_m7_router_smoke(smoke_client: TestClient) -> None:
    base = "/api/v1"
    assert smoke_client.get(f"{base}/spaces").status_code == 200
    assert smoke_client.get(f"{base}/sut-profiles").status_code == 200
    assert smoke_client.get(f"{base}/campaigns").status_code == 200
    assert smoke_client.get(f"{base}/campaigns/{_CID}").status_code == 200
    assert smoke_client.get(f"{base}/campaigns/{_CID}/progress").status_code == 200
    assert smoke_client.get(f"{base}/campaigns/{_CID}/runs").status_code == 200
    assert smoke_client.post(f"{base}/campaigns/{_CID}:analyze").status_code == 202
    assert smoke_client.get(f"{base}/campaigns/{_CID}/modes").status_code == 200
    assert smoke_client.get(f"{base}/campaigns/{_CID}/importance").status_code == 200
    assert smoke_client.get(f"{base}/campaigns/{_CID}/risk").status_code == 200
    assert smoke_client.get(f"{base}/runs/{_RID}").status_code == 200
    assert smoke_client.get(f"{base}/modes/{_MID}").status_code == 200
    assert smoke_client.get(f"{base}/experiments").status_code == 200
    assert smoke_client.get(f"{base}/workers").status_code == 200
    assert smoke_client.delete(f"{base}/campaigns/{_CID}").status_code == 204
    assert (
        smoke_client.get(
            f"{base}/campaigns/{_CID}/risk/slice",
            params={"x": "a", "y": "b"},
        ).status_code
        == 404
    )
    assert (
        smoke_client.post(
            f"{base}/reports",
            json={"kind": "campaign", "id": str(_CID)},
        ).status_code
        == 202
    )
