"""Bearer token auth and mutation content-type guard (T-080c)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from pydantic import SecretStr

from roboprobe.api.app import create_app
from roboprobe.api.auth import assert_bind_safe, require_json_mutation, require_token
from roboprobe.core.errors import ConfigError
from roboprobe.core.logging import REDACTED, redact_secrets
from roboprobe.core.settings import RoboProbeSettings

pytestmark = pytest.mark.unit


def _settings(tmp_path: Path, **api: object) -> RoboProbeSettings:
    return RoboProbeSettings(
        storage={
            "workdir_root": str(tmp_path / "w"),
            "artifact_root": str(tmp_path / "a"),
        },
        api={"host": "127.0.0.1", "cursor_secret": SecretStr("s"), **api},
        observability={"metrics_enabled": False},
    )


def test_auth_optional_when_no_token(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    app.state.readiness_failures = []
    client = TestClient(app)
    assert client.get("/api/v1/meta").status_code == 200


def test_auth_required_when_token_set(tmp_path: Path) -> None:
    settings = _settings(tmp_path, token=SecretStr("secret-token"))
    app = create_app(settings)
    app.state.readiness_failures = []
    client = TestClient(app)
    assert client.get("/api/v1/meta").status_code == 401
    assert client.get("/health/live").status_code == 200
    ok = client.get("/api/v1/meta", headers={"Authorization": "Bearer secret-token"})
    assert ok.status_code == 200
    bad = client.get("/api/v1/meta", headers={"Authorization": "Bearer wrong"})
    assert bad.status_code == 401
    assert bad.json()["code"] == "UNAUTHORIZED"


def test_query_token_rejected_on_non_sse(tmp_path: Path) -> None:
    settings = _settings(tmp_path, token=SecretStr("secret-token"))
    app = create_app(settings)
    client = TestClient(app)
    response = client.get("/api/v1/meta?token=secret-token")
    assert response.status_code == 401


def test_bind_address_requires_token() -> None:
    with pytest.raises((ConfigError, Exception)):
        RoboProbeSettings(api={"host": "0.0.0.0"})
    settings = RoboProbeSettings(api={"host": "0.0.0.0", "token": SecretStr("t")})
    assert_bind_safe(settings)


def test_form_encoded_post_415(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    router = APIRouter()

    @router.post("/_echo")
    def echo() -> dict[str, str]:
        return {"ok": "1"}

    app.include_router(
        router,
        prefix="/api/v1",
        dependencies=[Depends(require_token), Depends(require_json_mutation)],
    )
    client = TestClient(app)
    response = client.post(
        "/api/v1/_echo",
        data={"a": "b"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 415


def test_access_log_redacts_token() -> None:
    event = redact_secrets(
        None,
        "info",
        {"authorization": "Bearer secret-token", "token": "secret-token", "event": "api.request"},
    )
    assert event["authorization"] == REDACTED
    assert event["token"] == REDACTED
