"""Mode edits require current versions and confirmations enqueue work (T-082a)."""

from __future__ import annotations

from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tests.api.test_campaigns_crud import body
from tests.api.test_campaigns_crud import client as client  # noqa: PLC0414 - shared pytest fixture

from roboprobe.store.records import FailureModeRecord

pytestmark = pytest.mark.unit


def mode(client: TestClient) -> UUID:
    cid = UUID(client.post("/api/v1/campaigns", json=body()).json()["id"])
    mid = uuid4()
    row = FailureModeRecord(
        id=mid,
        campaign_id=cid,
        code="FM-01",
        label="Collision",
        primary_class="F-COL",
        class_mix={},
        size=1,
        param_ranges={},
        characteristic=(),
    )
    with client.app.state.services.uow_factory() as uow:
        uow.modes.upsert_modes(cid, [row], [])
        uow.commit()
    return mid


def test_html_label_roundtrip_and_stale_etag(client: TestClient) -> None:
    mid = mode(client)
    url = f"/api/v1/modes/{mid}"
    initial = client.get(url)
    updated = client.patch(
        url, json={"label": "<b>Collision</b>"}, headers={"If-Match": initial.headers["etag"]}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["label"] == "<b>Collision</b>"
    assert updated.json()["label_is_user"]
    stale = client.patch(
        url, json={"status": "fixed"}, headers={"If-Match": initial.headers["etag"]}
    )
    assert stale.status_code == 412


def test_duplicate_requires_target_and_labels_reject_control_characters(client: TestClient) -> None:
    mid = mode(client)
    for payload in ({"status": "duplicate"}, {"label": "bad\nlabel"}, {"label": " "}):
        response = client.patch(f"/api/v1/modes/{mid}", json=payload, headers={"If-Match": 'W/"1"'})
        assert response.status_code == 422


def test_duplicate_link_updates_with_status_and_keeps_versions_current(client: TestClient) -> None:
    mid = mode(client)
    with client.app.state.services.uow_factory() as uow:
        row = uow.modes.get(mid)
        other = row.model_copy(update={"id": uuid4(), "code": "FM-02"})
        uow.modes.upsert_modes(row.campaign_id, [row, other], [])
        uow.commit()

    url = f"/api/v1/modes/{mid}"
    initial = client.get(url)
    duplicate = client.patch(
        url,
        json={"status": "duplicate", "duplicate_of": "FM-02"},
        headers={"If-Match": initial.headers["etag"]},
    )
    assert duplicate.status_code == 200, duplicate.text
    assert client.get(url).json()["duplicate_of"] == "FM-02"
    reopened = client.patch(
        url,
        json={"status": "open"},
        headers={"If-Match": duplicate.headers["etag"]},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["duplicate_of"] is None
    assert client.get(url).headers["etag"] == reopened.headers["etag"]


def test_confirm_interaction_calls_service(client: TestClient) -> None:
    mid = mode(client)
    run_id = uuid4()
    service = Mock()
    service.request.return_value = [run_id]
    client.app.state.services.confirmations = service
    response = client.post(f"/api/v1/modes/{mid}:confirm-interaction")
    assert response.status_code == 202
    assert response.json()["run_ids"] == [str(run_id)]
    service.request.assert_called_once()
