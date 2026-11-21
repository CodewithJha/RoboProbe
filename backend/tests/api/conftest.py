"""HTTP API tests through the FastAPI test client.

Fixtures specific to this test layer go here (docs/18 §2).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from roboprobe.api.app import create_app
from roboprobe.core.metrics_registry import create_metrics
from roboprobe.core.settings import RoboProbeSettings

pytestmark = pytest.mark.unit


@dataclass
class StubServices:
    """Minimal services object for API unit tests (no real DB)."""

    settings: RoboProbeSettings
    engine: Any = None
    artifact_store: Any = None
    uow_factory: Any = None
    metrics: Any = field(default_factory=lambda: create_metrics(enabled=False))
    plugin_catalog: dict[str, Any] = field(
        default_factory=lambda: {
            "backends": [{"name": "kinematic2d", "capabilities": {"deterministic": True}}],
            "strategies": [
                {
                    "name": "S-RANDOM",
                    "description": "random",
                    "params_schema": {"type": "object"},
                }
            ],
            "oracles": [{"name": "O-CLEAR"}],
            "analyzers": [],
        }
    )

    def close(self) -> None:
        return None


@pytest.fixture
def api_settings(tmp_path: Path) -> RoboProbeSettings:
    return RoboProbeSettings(
        storage={
            "workdir_root": str(tmp_path / "w"),
            "artifact_root": str(tmp_path / "a"),
        },
        api={
            "host": "127.0.0.1",
            "cors_origins": ["http://localhost:5173"],
            "cursor_secret": SecretStr("test-cursor-secret"),
        },
        observability={"metrics_enabled": True},
    )


@pytest.fixture
def api_client(api_settings: RoboProbeSettings, tmp_path: Path) -> Iterator[TestClient]:
    """TestClient with stubbed services; override deps via ``client.app.dependency_overrides``."""
    (tmp_path / "a").mkdir(parents=True, exist_ok=True)
    app = create_app(api_settings)
    services = StubServices(settings=api_settings)
    # Ready check: pretend DB + migrations are fine.
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    conn.execute.return_value = None
    services.engine = engine
    app.state.services = services
    app.state.readiness_failures = []
    with TestClient(app) as client:
        yield client
