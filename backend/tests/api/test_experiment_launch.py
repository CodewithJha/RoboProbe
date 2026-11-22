"""Opt-in API experiment planning stages the full CRN campaign matrix."""

from __future__ import annotations

from http import HTTPStatus
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from tests.api.test_campaigns_crud import client as client  # noqa: PLC0414 - shared fixture

pytestmark = pytest.mark.unit
_URL = "/api/v1/experiments"
_DESIGN = {
    "schema_version": 1,
    "id": "launch_test",
    "backend": "kinematic2d",
    "space": {"id": "warehouse_v1"},
    "budget": 5,
    "seeds": {"root": 42, "count": 2},
    "strategies": [
        {"id": "S-RANDOM", "label": "A"},
        {"id": "S-RANDOM", "label": "B"},
    ],
    "metrics": ["MET-01", "MET-03"],
}


def test_design_registration_does_not_launch(client: TestClient) -> None:
    launch = Mock()
    client.app.state.services.experiment_jobs = launch
    response = client.post(_URL, json={"design": _DESIGN})
    assert response.status_code == HTTPStatus.CREATED
    assert response.json()["status"] == "CREATED"
    launch.submit.assert_not_called()


def test_explicit_launch_plans_common_seeds_and_enqueues_the_runner(client: TestClient) -> None:
    launch = Mock()
    client.app.state.services.experiment_jobs = launch
    response = client.post(_URL, json={"design": _DESIGN, "start": True})
    assert response.status_code == HTTPStatus.CREATED, response.text
    experiment_id = UUID(response.json()["id"])
    launch.submit.assert_called_once()
    assert launch.submit.call_args.args[0] == experiment_id
    cells = client.get(f"{_URL}/{experiment_id}").json()["cells"]
    assert len(cells) == 4
    for rep in (0, 1):
        same_rep = [cell for cell in cells if cell["rep"] == rep]
        assert len(same_rep) == 2
        assert same_rep[0]["seed"] == same_rep[1]["seed"]
    assert len({cell["campaign_id"] for cell in cells}) == 4


def test_launch_rejects_a_matrix_larger_than_the_api_limit(client: TestClient) -> None:
    launch = Mock()
    client.app.state.services.experiment_jobs = launch
    design = {**_DESIGN, "seeds": {"root": 42, "count": 10**12}}
    response = client.post(_URL, json={"design": design, "start": True})
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert client.get(_URL).json()["items"] == []
    launch.submit.assert_not_called()
