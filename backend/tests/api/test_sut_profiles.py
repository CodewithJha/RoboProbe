"""Tests for ``/sut-profiles`` routers (T-081a; docs/10 §4, docs/12 §2)."""

from __future__ import annotations

import json
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from roboprobe.api.app import create_app
from roboprobe.core.settings import RoboProbeSettings

pytestmark = pytest.mark.unit

API = "/api/v1"
OVERSIZE_BYTES = 10 * 1024 * 1024 + 1

K2D_PROFILE = """
schema_version: 1
id: k2d_api
backend: kinematic2d
config:
  model_file: configs/backends/kinematic2d_v1.yaml
  gain_overrides: {}
"""

BAD_BACKEND = """
schema_version: 1
id: bad_api
backend: no_such_backend
config: {}
"""


def post_profile(
    client: TestClient, body: bytes | str, media_type: str = "application/yaml"
) -> Any:
    """POST a raw profile document with an explicit media type."""
    payload = body.encode("utf-8") if isinstance(body, str) else body
    return client.post(f"{API}/sut-profiles", content=payload, headers={"content-type": media_type})


def test_create_profile_returns_hash_and_config(upload_client: TestClient) -> None:
    response = post_profile(upload_client, K2D_PROFILE)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] == "k2d_api"
    assert body["backend"] == "kinematic2d"
    assert len(body["config_hash"]) == 64
    assert body["config"]["model_file"] == "configs/backends/kinematic2d_v1.yaml"
    assert body["config"]["gain_overrides"] == {}


def test_identical_repost_is_idempotent(upload_client: TestClient, fake_db: Any) -> None:
    first = post_profile(upload_client, K2D_PROFILE)
    second = post_profile(upload_client, K2D_PROFILE)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["config_hash"] == first.json()["config_hash"]
    assert len(fake_db.sut_profiles) == 1


def test_same_id_with_a_different_config_is_rejected(upload_client: TestClient) -> None:
    assert post_profile(upload_client, K2D_PROFILE).status_code == 201
    changed = K2D_PROFILE.replace(
        "gain_overrides: {}", "gain_overrides: {controller.lookahead_m: 0.8}"
    )

    response = post_profile(upload_client, changed)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "immutable" in body["detail"]


@pytest.mark.parametrize("media_type", ["application/json", "application/x-yaml", "text/yaml"])
def test_json_and_yaml_aliases_are_accepted(upload_client: TestClient, media_type: str) -> None:
    document = yaml.safe_load(K2D_PROFILE)
    document["id"] = "k2d_api_alt"
    payload = json.dumps(document)

    response = post_profile(upload_client, payload, media_type=media_type)

    assert response.status_code == 201, response.text
    assert response.json()["id"] == "k2d_api_alt"


def test_unknown_backend_returns_422_with_pointer(upload_client: TestClient) -> None:
    response = post_profile(upload_client, BAD_BACKEND)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert any(error["pointer"] == "/backend" for error in body["errors"])


def test_oversized_body_returns_413(upload_client: TestClient) -> None:
    response = post_profile(upload_client, b"# pad\n" * (OVERSIZE_BYTES // 6 + 1))

    assert response.status_code == 413


def test_list_paginates_profiles(upload_client: TestClient) -> None:
    for profile_id in ("a_profile", "b_profile"):
        document = yaml.safe_load(K2D_PROFILE)
        document["id"] = profile_id
        assert post_profile(upload_client, json.dumps(document)).status_code == 201

    first = upload_client.get(f"{API}/sut-profiles", params={"limit": 1})
    assert first.status_code == 200
    assert [item["id"] for item in first.json()["items"]] == ["a_profile"]
    cursor = first.json()["next_cursor"]
    assert cursor

    second = upload_client.get(f"{API}/sut-profiles", params={"limit": 1, "cursor": cursor})
    assert second.status_code == 200
    assert [item["id"] for item in second.json()["items"]] == ["b_profile"]
    assert second.json()["next_cursor"] is None


def test_openapi_documents_yaml_and_json_bodies(api_settings: RoboProbeSettings) -> None:
    schema = create_app(api_settings).openapi()

    content = schema["paths"][f"{API}/sut-profiles"]["post"]["requestBody"]["content"]
    assert {"application/yaml", "application/json"} <= set(content)
