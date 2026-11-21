"""Campaign API invariants and lifecycle matrix (T-081b/c, FR-API-001)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import structlog.testing
import yaml
from fastapi.testclient import TestClient
from tests.fakes.store import InMemoryUnitOfWork, _Modes, _Runs

from roboprobe.cli import campaign as cli_campaign
from roboprobe.core.types import CampaignStatus
from roboprobe.runner.lifecycle import ALLOWED, IDEMPOTENT, CampaignCommand, CampaignService
from roboprobe.scenario.repo_root import discover_repo_root

pytestmark = pytest.mark.unit
API = "/api/v1/campaigns"


class _Idempotency:
    def __init__(self) -> None:
        self.rows: dict[str, Any] = {}

    def get(self, key: str) -> Any:
        return self.rows.get(key)

    def put(self, row: Any) -> None:
        self.rows[row.key] = row


@pytest.fixture
def client(api_client: TestClient) -> TestClient:
    uow = InMemoryUnitOfWork()
    services = api_client.app.state.services
    services.uow_factory = lambda: uow
    services.campaigns = CampaignService(lambda: uow)
    services.space_root = discover_repo_root()
    services.idempotency = _Idempotency()
    return api_client


def body(**overrides: object) -> dict[str, object]:
    return {
        "space": {"id": "warehouse_v1"},
        "backend": "kinematic2d",
        "strategy": {"id": "S-RANDOM", "seed": 42},
        "budget": 5,
        **overrides,
    }


def test_create_returns_location_and_snapshot(client: TestClient) -> None:
    response = client.post(API, json=body())
    assert response.status_code == 201, response.text
    assert response.headers["location"] == f"{API}/{response.json()['id']}"
    assert "allow_repeats" in response.json()["strategy"]["params"]


def test_start_true_commits_before_lifecycle(client: TestClient) -> None:
    response = client.post(API, json=body(start=True))
    assert response.status_code == 201, response.text
    assert client.get(f"{API}/{response.json()['id']}").json()["status"] == "RUNNING"


def test_idempotency_key_replays_response_and_rejects_other_body(client: TestClient) -> None:
    headers = {"Idempotency-Key": "campaign-create"}
    first = client.post(API, json=body(), headers=headers)
    second = client.post(API, json=body(), headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert len(client.get(API).json()["items"]) == 1
    assert client.post(API, json=body(budget=6), headers=headers).status_code == 422


@pytest.mark.parametrize(
    "override",
    [
        {"budget": 0},
        {"repeats": 0},
        {"batch_size": 0},
        {"backend": "unknown"},
        {"space": {"id": "../../outside"}},
        {"pins": {"unknown": 1}},
        {"strategy": {"id": "unknown"}},
    ],
)
def test_invalid_create_returns_422(client: TestClient, override: dict[str, object]) -> None:
    response = client.post(API, json=body(**override))
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "command",
    [CampaignCommand.START, CampaignCommand.PAUSE, CampaignCommand.RESUME, CampaignCommand.CANCEL],
)
@pytest.mark.parametrize("status", list(CampaignStatus))
def test_http_lifecycle_matrix(
    client: TestClient, command: CampaignCommand, status: CampaignStatus
) -> None:
    created = client.post(API, json=body()).json()

    cid = UUID(created["id"])
    with client.app.state.services.uow_factory() as uow:
        uow.campaigns.set_status(cid, status)
        uow.commit()
    response = client.post(f"{API}/{cid}:{command.value}")
    expected = ALLOWED.get((status, command), IDEMPOTENT.get((status, command)))
    if expected is None:
        assert response.status_code == 409, response.text
    else:
        assert response.status_code == 202, response.text
        assert response.json()["status"] == expected.value


def test_running_campaign_cannot_be_deleted(client: TestClient) -> None:
    created = client.post(API, json=body(start=True)).json()
    assert client.delete(f"{API}/{created['id']}").status_code == 409


def test_manual_runs_validate_and_use_real_scenario_hash(client: TestClient) -> None:
    created = client.post(API, json=body(pins={"robot.max_speed": 0.3})).json()
    path = f"{API}/{created['id']}/runs"
    bad = client.post(path, json={"values": {"robot.max_speed": 0.6}})
    assert bad.status_code == 422
    assert bad.json()["errors"]
    headers = {"Idempotency-Key": "manual"}
    good = client.post(path, json={"values": {}, "repeats": 2}, headers=headers)
    repeated = client.post(path, json={"values": {}, "repeats": 2}, headers=headers)
    assert good.status_code == 201, good.text
    assert good.json() == repeated.json()
    assert len(good.json()["run_ids"]) == 2
    runs = client.get(path).json()["items"]
    assert len(runs) == 2
    assert runs[0]["scenario"]["hash"] != "manual"
    assert runs[0]["scenario"]["values"]["robot.max_speed"] == 0.3
    assert runs[0]["seed"] != runs[1]["seed"]


def test_manual_repeat_limit(client: TestClient) -> None:
    created = client.post(API, json=body()).json()
    response = client.post(f"{API}/{created['id']}/runs", json={"values": {}, "repeats": 10**12})
    assert response.status_code == 422


def test_stale_campaign_patch_is_rejected(client: TestClient) -> None:
    created = client.post(API, json=body()).json()
    path = f"{API}/{created['id']}"
    etag = client.get(path).headers["etag"]
    assert (
        client.patch(path, json={"name": "Renamed"}, headers={"If-Match": etag}).status_code == 200
    )
    assert client.patch(path, json={"name": "Stale"}, headers={"If-Match": etag}).status_code == 412


def test_cli_and_http_share_campaign_snapshots(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    payload = body(oracle_overrides={"loc": {"e_max": 0.4}})
    http_response = client.post(API, json=payload)
    assert http_response.status_code == 201
    services = client.app.state.services
    services.make_uow = services.uow_factory
    monkeypatch.setattr(cli_campaign, "build_cli_services", lambda _: services)
    monkeypatch.setattr(cli_campaign, "register_space", lambda *a, **kw: None)
    config = tmp_path / "campaign.yaml"
    config.write_text(yaml.safe_dump({"schema_version": 1, **payload}))
    cli_id = cli_campaign.create_campaign_from_config(config, services.settings)
    with services.uow_factory() as uow:
        http = uow.campaigns.get(UUID(http_response.json()["id"]))
        cli = uow.campaigns.get(cli_id)
    for field in (
        "space_version",
        "sut_profile_id",
        "strategy_params",
        "seed",
        "oracle_config",
        "pins",
    ):
        assert getattr(http, field) == getattr(cli, field)


@pytest.mark.parametrize("start", [False, True])
def test_failed_idempotency_persistence_rolls_back_creation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, start: bool
) -> None:
    def fail(*args, **kwargs):
        message = "simulate cache persistence failure"
        raise RuntimeError(message)

    monkeypatch.setattr("roboprobe.api.campaign_idempotency.remember", fail)
    with structlog.testing.capture_logs(), pytest.raises(RuntimeError, match="cache persistence"):
        client.post(API, json=body(start=start), headers={"Idempotency-Key": "atomic"})
    with client.app.state.services.uow_factory() as uow:
        assert not uow.campaigns.list().items


def test_idempotency_replay_uses_database_after_process_cache_reset(client: TestClient) -> None:
    headers = {"Idempotency-Key": "durable"}
    first = client.post(API, json=body(start=True), headers=headers)
    client.app.state.services.idempotency = _Idempotency()
    replay = client.post(API, json=body(start=True), headers=headers)
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert replay.headers["location"] == first.headers["location"]
    assert replay.json()["status"] == "RUNNING"


def test_campaign_filters_precede_stable_pagination(client: TestClient) -> None:
    ids = []
    for name in ["first", "second", "third"]:
        response = client.post(API, json=body(name=name))
        assert response.status_code == 201
        ids.append(response.json()["id"])
    first = client.get(
        API, params={"limit": 1, "strategy": "S-RANDOM", "backend": "kinematic2d"}
    ).json()
    second = client.get(
        API,
        params={
            "limit": 1,
            "cursor": first["next_cursor"],
            "strategy": "S-RANDOM",
            "backend": "kinematic2d",
        },
    ).json()
    third = client.get(API, params={"limit": 1, "cursor": second["next_cursor"]}).json()
    assert [page["items"][0]["id"] for page in [first, second, third]] == list(reversed(ids))
    assert third["next_cursor"] is None
    assert not client.get(API, params={"status": "RUNNING"}).json()["items"]
    assert not client.get(API, params={"strategy": "unknown"}).json()["items"]
    assert not client.get(API, params={"backend": "unknown"}).json()["items"]
    assert client.get(API, params={"cursor": "invalid"}).status_code == 422


def test_campaign_list_reads_page_aggregates_without_loading_runs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = client.post(API, json=body()).json()
    cid = UUID(created["id"])
    monkeypatch.setattr(
        _Runs, "counts_for_campaigns", lambda self, ids: {cid: {"pending": 10000}}, raising=False
    )
    monkeypatch.setattr(_Modes, "counts_for_campaigns", lambda self, ids: {cid: 3}, raising=False)

    def forbidden(*args, **kwargs):
        pytest.fail("list must not load individual runs or mode rows")

    monkeypatch.setattr(_Runs, "list_for_campaign", forbidden)
    monkeypatch.setattr(_Modes, "list_for_campaign", forbidden)
    response = client.get(API)
    assert response.status_code == 200
    assert response.json()["items"][0]["counts"]["pending"] == 10000
    assert response.json()["items"][0]["modes_found"] == 3
