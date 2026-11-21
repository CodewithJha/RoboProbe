"""HTTP API tests through the FastAPI test client.

Fixtures specific to this test layer go here (docs/18 §2).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
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
from roboprobe.store.pagination import Page

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

    campaigns: Any = None
    analysis: Any = None
    report_jobs: Any = None
    space_root: Path = field(default_factory=Path.cwd)

    def close(self) -> None:
        return None


@dataclass
class FakeDatabase:
    """Process-local row store shared by fake repositories (no database required)."""

    spaces: dict[tuple[str, str], Any] = field(default_factory=dict)
    sut_profiles: dict[str, Any] = field(default_factory=dict)


class FakeSpaceRepo:
    """In-memory ``SpaceRepo`` mirroring the SQL keyset pagination."""

    def __init__(self, db: FakeDatabase) -> None:
        """Bind the repository to ``db``."""
        self._db = db

    def get(self, space_id: str, version: str) -> Any | None:
        return self._db.spaces.get((space_id, version))

    def add(self, record: Any) -> None:
        self._db.spaces[(record.id, record.version)] = record

    def list(self, *, limit: int | None = None, cursor: str | None = None) -> Page[Any]:
        size = 50 if limit is None else limit
        keys = sorted(self._db.spaces)
        start = 0
        if cursor is not None:
            sid, _, ver = cursor.partition("\t")
            key = (sid, ver)
            start = keys.index(key) + 1 if key in keys else len(keys)
        rows = [self._db.spaces[key] for key in keys[start : start + size]]
        nxt = None
        if len(keys) > start + size:
            nxt = f"{rows[-1].id}\t{rows[-1].version}"
        return Page(items=tuple(rows), next_cursor=nxt)


class FakeSutProfileRepo:
    """In-memory ``SutProfileRepo``."""

    def __init__(self, db: FakeDatabase) -> None:
        """Bind the repository to ``db``."""
        self._db = db

    def get(self, profile_id: str) -> Any | None:
        return self._db.sut_profiles.get(profile_id)

    def add(self, record: Any) -> None:
        self._db.sut_profiles[record.id] = record

    def list(self, *, limit: int | None = None, cursor: str | None = None) -> Page[Any]:
        size = 50 if limit is None else limit
        ids = sorted(self._db.sut_profiles)
        if cursor is not None:
            ids = [profile_id for profile_id in ids if profile_id > cursor]
        rows: Sequence[Any] = [self._db.sut_profiles[profile_id] for profile_id in ids[:size]]
        nxt = None
        if len(ids) > size:
            nxt = rows[-1].id
        return Page(items=tuple(rows), next_cursor=nxt)


class FakeUnitOfWork:
    """Context-manager unit of work backed by :class:`FakeDatabase`."""

    def __init__(self, db: FakeDatabase) -> None:
        """Expose the fake repositories for ``db``."""
        self.spaces = FakeSpaceRepo(db)
        self.sut_profiles = FakeSutProfileRepo(db)
        self._committed = False

    def __enter__(self) -> FakeUnitOfWork:
        """Enter the unit of work."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Commit on a clean exit, mirroring ``SqlAlchemyUnitOfWork``."""
        if exc[0] is None and not self._committed:
            self.commit()

    def commit(self) -> None:
        """Mark the transaction as committed."""
        self._committed = True


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


def build_client(
    settings: RoboProbeSettings, tmp_path: Path, services: StubServices
) -> Iterator[TestClient]:
    """Create a TestClient with stubbed services and a healthy readiness probe."""
    (tmp_path / "a").mkdir(parents=True, exist_ok=True)
    app = create_app(settings)
    # Unit tests have no database; the outbox listener stays stopped.
    app.state.event_hub_autostart = False
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


@pytest.fixture
def api_client(api_settings: RoboProbeSettings, tmp_path: Path) -> Iterator[TestClient]:
    """TestClient with stubbed services; override deps via ``client.app.dependency_overrides``."""
    yield from build_client(api_settings, tmp_path, StubServices(settings=api_settings))


@pytest.fixture
def fake_db() -> FakeDatabase:
    """Empty in-memory store for catalogue-router tests."""
    return FakeDatabase()


@pytest.fixture
def upload_client(
    api_settings: RoboProbeSettings,
    tmp_path: Path,
    fake_db: FakeDatabase,
) -> Iterator[TestClient]:
    """TestClient whose unit of work is the in-memory fake (spaces, SUT profiles)."""
    services = StubServices(
        settings=api_settings,
        uow_factory=lambda: FakeUnitOfWork(fake_db),
        space_root=Path(__file__).resolve().parents[3],
    )
    yield from build_client(api_settings, tmp_path, services)
