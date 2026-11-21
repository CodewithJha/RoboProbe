"""TM-06: disallowed origins and form posts are rejected (T-080a, T-080c, T-109)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from pydantic import SecretStr

from roboprobe.api.app import create_app
from roboprobe.api.auth import require_json_mutation, require_token
from roboprobe.core.settings import RoboProbeSettings

pytestmark = pytest.mark.security


def _app(tmp_path: Path) -> TestClient:
    settings = RoboProbeSettings(
        storage={"workdir_root": str(tmp_path / "w"), "artifact_root": str(tmp_path / "a")},
        api={"host": "127.0.0.1", "cursor_secret": SecretStr("s")},
        observability={"metrics_enabled": False},
    )
    app = create_app(settings)
    router = APIRouter()

    @router.post("/_echo")
    def echo() -> dict[str, str]:
        return {"ok": "1"}

    app.include_router(
        router,
        prefix="/api/v1",
        dependencies=[Depends(require_token), Depends(require_json_mutation)],
    )
    return TestClient(app)


def test_disallowed_origin_has_no_allow_header(tmp_path: Path) -> None:
    client = _app(tmp_path)
    response = client.get("/api/v1/meta", headers={"Origin": "https://evil.example"})
    assert response.headers.get("access-control-allow-origin") is None


def test_form_post_rejected(tmp_path: Path) -> None:
    client = _app(tmp_path)
    response = client.post(
        "/api/v1/_echo",
        content="a=1",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 415
