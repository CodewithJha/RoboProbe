"""Tests for ``/spaces`` routers (T-081a; docs/12 §2, docs/12 §6, TM-02, TM-13)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from roboprobe.api.app import create_app
from roboprobe.core.settings import RoboProbeSettings

pytestmark = pytest.mark.unit

API = "/api/v1"
REPO_ROOT = Path(__file__).resolve().parents[3]
WAREHOUSE = REPO_ROOT / "configs" / "scenario_spaces" / "warehouse_v1.yaml"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "spaces"
INVALID_HIGH = FIXTURES / "invalid" / "high_not_above_low.yaml"
ESCAPING_TASK = FIXTURES / "invalid" / "task_escapes_base_dir.yaml"
OVERSIZE_BYTES = 10 * 1024 * 1024 + 1

BILLION_LAUGHS = b"""
schema_version: 1
id: laughs
name: Billion laughs
task: tasks/warehouse_delivery_v1.yaml
l0: &l0 [a, a, a, a, a, a, a, a, a, a]
l1: &l1 [*l0, *l0, *l0, *l0, *l0, *l0, *l0, *l0, *l0, *l0]
l2: &l2 [*l1, *l1, *l1, *l1, *l1, *l1, *l1, *l1, *l1, *l1]
l3: &l3 [*l2, *l2, *l2, *l2, *l2, *l2, *l2, *l2, *l2, *l2]
l4: &l4 [*l3, *l3, *l3, *l3, *l3, *l3, *l3, *l3, *l3, *l3]
"""


def post_yaml(client: TestClient, body: bytes | str, media_type: str = "application/yaml") -> Any:
    """POST a raw body with an explicit media type."""
    payload = body.encode("utf-8") if isinstance(body, str) else body
    return client.post(f"{API}/spaces", content=payload, headers={"content-type": media_type})


def post_validate(client: TestClient, body: bytes | str) -> Any:
    """POST a raw body to ``/spaces/validate``."""
    payload = body.encode("utf-8") if isinstance(body, str) else body
    return client.post(
        f"{API}/spaces/validate",
        content=payload,
        headers={"content-type": "application/yaml"},
    )


def warehouse_document() -> dict[str, Any]:
    """Parsed shipped warehouse space (valid against the API base directory)."""
    document = yaml.safe_load(WAREHOUSE.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_register_yaml_returns_created_version(upload_client: TestClient) -> None:
    response = post_yaml(upload_client, WAREHOUSE.read_bytes())

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] == "warehouse_v1"
    assert body["name"].startswith("Warehouse delivery")
    assert len(body["version"]) == 12
    assert body["definition"]["id"] == "warehouse_v1"
    assert body["schema_version"] == 1


def test_reregistering_identical_content_is_idempotent(
    upload_client: TestClient, fake_db: Any
) -> None:
    first = post_yaml(upload_client, WAREHOUSE.read_bytes())
    second = post_yaml(upload_client, WAREHOUSE.read_bytes())

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["version"] == first.json()["version"]
    assert len(fake_db.spaces) == 1


def test_changed_content_creates_a_new_version(upload_client: TestClient, fake_db: Any) -> None:
    first = post_yaml(upload_client, WAREHOUSE.read_bytes())
    document = warehouse_document()
    document["name"] = "Warehouse delivery (renamed)"
    second = post_yaml(upload_client, yaml.safe_dump(document, sort_keys=False))

    assert second.status_code == 201
    assert second.json()["version"] != first.json()["version"]
    assert len(fake_db.spaces) == 2


def test_register_json_body(upload_client: TestClient) -> None:
    payload = json.dumps(warehouse_document())

    response = post_yaml(upload_client, payload, media_type="application/json")

    assert response.status_code == 201, response.text
    assert response.json()["id"] == "warehouse_v1"


def test_invalid_space_returns_422_space_invalid_with_pointers(upload_client: TestClient) -> None:
    response = post_yaml(upload_client, INVALID_HIGH.read_bytes())

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "SPACE_INVALID"
    pointers = {error["pointer"] for error in body["errors"]}
    assert "/parameters/2/high" in pointers


def test_task_path_escaping_the_base_directory_is_rejected(upload_client: TestClient) -> None:
    response = post_yaml(upload_client, ESCAPING_TASK.read_bytes())

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "SPACE_INVALID"
    assert any(error["pointer"] == "/task" for error in body["errors"])


def test_oversized_body_returns_413(upload_client: TestClient) -> None:
    response = post_yaml(upload_client, b"# pad\n" * (OVERSIZE_BYTES // 6 + 1))

    assert response.status_code == 413


def test_billion_laughs_is_rejected_without_expansion(upload_client: TestClient) -> None:
    response = post_yaml(upload_client, BILLION_LAUGHS)

    assert response.status_code == 422
    assert "too many aliases" in response.json()["detail"]


def test_validate_valid_space_returns_dimension(upload_client: TestClient) -> None:
    response = post_validate(upload_client, WAREHOUSE.read_bytes())

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["dimension"] == 6
    assert len(body["enabled_params"]) == 6
    assert "obstacle.along_path" not in body["enabled_params"]
    assert body["errors"] == []


def test_validate_invalid_space_returns_200_with_errors(upload_client: TestClient) -> None:
    response = post_validate(upload_client, INVALID_HIGH.read_bytes())

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["dimension"] is None
    assert any(error["pointer"] == "/parameters/2/high" for error in body["errors"])


def test_list_paginates_and_get_returns_the_stored_definition(
    upload_client: TestClient,
) -> None:
    first = post_yaml(upload_client, WAREHOUSE.read_bytes()).json()
    document = warehouse_document()
    document["name"] = "Warehouse delivery (renamed)"
    second = post_yaml(upload_client, yaml.safe_dump(document, sort_keys=False)).json()

    page_one = upload_client.get(f"{API}/spaces", params={"limit": 1})
    assert page_one.status_code == 200
    body_one = page_one.json()
    assert len(body_one["items"]) == 1
    assert body_one["items"][0]["dimension"] == 6
    assert body_one["next_cursor"]

    page_two = upload_client.get(
        f"{API}/spaces", params={"limit": 1, "cursor": body_one["next_cursor"]}
    )
    assert page_two.status_code == 200
    assert len(page_two.json()["items"]) == 1
    assert page_two.json()["next_cursor"] is None

    stored = upload_client.get(f"{API}/spaces/warehouse_v1/versions/{first['version']}")
    assert stored.status_code == 200
    assert stored.json()["version"] == first["version"]
    assert stored.json()["definition"]["name"] == "Warehouse delivery - single injected pallet"
    assert second["version"] != first["version"]


def test_get_unknown_version_returns_404(upload_client: TestClient) -> None:
    response = upload_client.get(f"{API}/spaces/nope/versions/000000000000")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_openapi_documents_yaml_and_json_bodies(api_settings: RoboProbeSettings) -> None:
    app = create_app(api_settings)
    schema = app.openapi()

    content = schema["paths"][f"{API}/spaces"]["post"]["requestBody"]["content"]
    assert {"application/yaml", "application/json"} <= set(content)
    validate = schema["paths"][f"{API}/spaces/validate"]["post"]["requestBody"]["content"]
    assert {"application/yaml", "application/json"} <= set(validate)


def test_upload_uses_configured_task_root(upload_client: TestClient, tmp_path: Path) -> None:
    upload_client.app.state.services.space_root = tmp_path
    response = post_validate(upload_client, WAREHOUSE.read_bytes())
    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert any(error["pointer"] == "/task" for error in response.json()["errors"])


def test_list_honors_configured_pagination_cap(upload_client: TestClient) -> None:
    settings = upload_client.app.state.settings
    upload_client.app.state.settings = settings.model_copy(
        update={
            "api": settings.api.model_copy(update={"page_limit_default": 1, "page_limit_max": 2})
        }
    )
    for name in ("first", "second", "third"):
        document = warehouse_document()
        document["name"] = name
        assert post_yaml(upload_client, yaml.safe_dump(document)).status_code == 201
    assert len(upload_client.get(f"{API}/spaces").json()["items"]) == 1
    assert len(upload_client.get(f"{API}/spaces?limit=100").json()["items"]) == 2
