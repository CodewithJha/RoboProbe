"""TM-01: missing or wrong bearer token is rejected (T-080c, T-109)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from roboprobe.api.app import create_app
from roboprobe.core.settings import RoboProbeSettings

pytestmark = pytest.mark.security


def _settings(tmp_path: Path) -> RoboProbeSettings:
    return RoboProbeSettings(
        storage={"workdir_root": str(tmp_path / "w"), "artifact_root": str(tmp_path / "a")},
        api={
            "host": "127.0.0.1",
            "token": SecretStr("secret-token"),
            "cursor_secret": SecretStr("s"),
        },
        observability={"metrics_enabled": False},
    )


def test_missing_and_wrong_token(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    client = TestClient(app)
    missing = client.get("/api/v1/meta")
    assert missing.status_code == 401
    assert missing.json()["code"] == "UNAUTHORIZED"
    wrong = client.get("/api/v1/meta", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    ok = client.get("/api/v1/meta", headers={"Authorization": "Bearer secret-token"})
    assert ok.status_code == 200
    assert "secret-token" not in ok.text
