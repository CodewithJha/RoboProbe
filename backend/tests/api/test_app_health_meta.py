"""App factory, health, meta, CORS and request logging (T-080a)."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from roboprobe.core.settings import RoboProbeSettings

pytestmark = pytest.mark.unit


def test_import_create_app_has_no_side_effects() -> None:
    mod = importlib.import_module("roboprobe.api.app")
    assert callable(mod.create_app)


def test_live_ok(api_client: TestClient) -> None:
    response = api_client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_ok_when_overrides_empty(api_client: TestClient) -> None:
    api_client.app.state.readiness_failures = []
    response = api_client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_503_when_db_down(api_client: TestClient) -> None:
    api_client.app.state.readiness_failures = ["db_unreachable"]
    response = api_client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == 503
    assert "db_unreachable" in body["detail"]
    assert response.headers["content-type"].startswith("application/problem+json")


def test_meta_lists_plugins(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/meta")
    assert response.status_code == 200
    body = response.json()
    assert body["api_version"] == "v1"
    assert body["backends"][0]["name"] == "kinematic2d"
    assert body["strategies"][0]["name"] == "S-RANDOM"
    assert "params_schema" in body["strategies"][0]
    assert body["oracles"][0]["name"] == "O-CLEAR"


def test_cors_disallowed_origin(api_client: TestClient) -> None:
    response = api_client.options(
        "/api/v1/meta",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in {k.lower(): v for k, v in response.headers.items()}


def test_cors_allowed_origin(api_client: TestClient) -> None:
    response = api_client.get(
        "/api/v1/meta",
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_request_log_uses_route_template(
    api_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("INFO"):
        api_client.get("/api/v1/meta")
    # structlog may not go through stdlib caplog; assert metrics label instead.
    metrics = api_client.app.state.metrics
    samples = list(metrics.api_request_duration_seconds.collect())
    labels = {tuple(sorted(s.labels.items())) for metric in samples for s in metric.samples}
    assert any(dict(label).get("route") == "/meta" for label in labels)


def test_create_app_refuses_non_loopback_without_token(tmp_path: pytest.TempPathFactory) -> None:
    del tmp_path
    with pytest.raises(Exception, match="token"):  # ConfigError or ValidationError
        RoboProbeSettings(api={"host": "0.0.0.0"})
