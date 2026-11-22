"""Replay source identity and portable scenario export (T-082c)."""

from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from tests.api.test_campaigns_crud import body
from tests.api.test_campaigns_crud import client as client  # noqa: PLC0414 - shared fixture

from roboprobe.core.types import RunStatus
from roboprobe.scenario.regression import load_regression

pytestmark = pytest.mark.unit


def test_export_round_trips_and_replay_preserves_source(client: TestClient, tmp_path: Path) -> None:
    campaign_id = client.post("/api/v1/campaigns", json=body()).json()["id"]
    created = client.post(f"/api/v1/campaigns/{campaign_id}/runs", json={"values": {}})
    assert created.status_code == 201, created.text
    source_id = UUID(created.json()["run_ids"][0])
    with client.app.state.services.uow_factory() as uow:
        source = uow.runs.get(source_id)
        assert source is not None
        uow.runs.import_many([source.model_copy(update={"status": RunStatus.DONE})])
        uow.commit()

    yaml_response = client.get(f"/api/v1/runs/{source_id}/scenario.yaml")
    assert yaml_response.status_code == 200, yaml_response.text
    assert yaml_response.headers["content-type"].startswith("application/yaml")
    exported = tmp_path / "scenario.yaml"
    exported.write_bytes(yaml_response.content)
    assert load_regression(exported).scenario.scenario_hash == source.scenario_hash

    replay_url = f"/api/v1/runs/{source_id}:replay"
    for fresh in (False, True):
        response = client.post(replay_url, json={"repeats": 1, "fresh_seeds": fresh})
        assert response.status_code == 202, response.text
        replay_id = UUID(response.json()["run_ids"][0])
        with client.app.state.services.uow_factory() as uow:
            replay = uow.runs.get(replay_id)
        assert replay is not None and replay.replay_of == source_id
        assert replay.scenario_hash == source.scenario_hash
        assert (replay.seed != source.seed) is fresh
