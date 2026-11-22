"""Exercise the committed T-107 seed through PostgreSQL and the FastAPI routes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from http import HTTPStatus
from pathlib import Path
from time import perf_counter
from typing import Any, Final
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from psycopg import sql
from sqlalchemy.engine import make_url
from tests.fixtures.db.load_seed import _postgres_dsn, load_seed

from roboprobe.api.app import create_app
from roboprobe.cli.db import upgrade_head
from roboprobe.core.settings import load_settings

pytestmark = pytest.mark.integration

_REPO = Path(__file__).resolve().parents[3]
_WEB_FIXTURES = _REPO / "web" / "src" / "test" / "fixtures"
_OPENAPI = _REPO / "api" / "openapi.json"
_EXPECTED_MODES: Final = 3
_EXPECTED_COUNTS: Final = (1, 60, _EXPECTED_MODES, 1, 1, 1)
_MAX_RESTORE_SECONDS: Final = 10.0


@pytest.fixture
def seed_database_url(postgres_url: str) -> Iterator[str]:
    """Allocate a database that cannot disturb other integration tests."""
    database_name = f"seed_test_{uuid4().hex}"
    identifier = sql.Identifier(database_name)
    with psycopg.connect(_postgres_dsn(postgres_url), autocommit=True) as admin:
        try:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(identifier))
        except psycopg.errors.InsufficientPrivilege:
            pytest.skip("seed integration test requires permission to create a scratch database")
        try:
            yield (
                make_url(postgres_url)
                .set(database=database_name)
                .render_as_string(hide_password=False)
            )
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(identifier))


def _verify_database(database_url: str, artifact_root: Path) -> tuple[UUID, UUID, set[UUID]]:
    with psycopg.connect(_postgres_dsn(database_url)) as connection:
        counts = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM campaigns),
                (SELECT count(*) FROM runs),
                (SELECT count(*) FROM failure_modes),
                (SELECT count(*) FROM risk_maps),
                (SELECT count(*) FROM analyses),
                (SELECT count(*) FROM experiments)
            """
        ).fetchone()
        assert counts == _EXPECTED_COUNTS

        campaign = connection.execute("SELECT id, experiment_id FROM campaigns").fetchone()
        assert campaign is not None
        campaign_id, experiment_id = campaign
        assert experiment_id is not None
        medoids = {
            run_id for (run_id,) in connection.execute("SELECT medoid_run_id FROM failure_modes")
        }
        artefacts = connection.execute(
            "SELECT kind, run_id, rel_path, size_bytes, sha256 FROM artifacts"
        ).fetchall()

    traces = [run_id for kind, run_id, _, _, _ in artefacts if kind == "trace"]
    assert len(traces) == len(medoids) == _EXPECTED_MODES
    assert set(traces) == medoids and None not in medoids
    extracted_paths = {
        file.relative_to(artifact_root).as_posix()
        for file in artifact_root.rglob("*")
        if file.is_file()
    }
    assert extracted_paths == {relative_name for _, _, relative_name, _, _ in artefacts}
    for _, _, relative_name, size, digest in artefacts:
        file = (artifact_root / relative_name).resolve()
        assert file.is_relative_to(artifact_root.resolve())
        assert file.stat().st_size == size
        with file.open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == digest
    return campaign_id, experiment_id, medoids


def _web_fixture(name: str) -> dict[str, Any]:
    return json.loads((_WEB_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _check_api(
    client: TestClient,
    *,
    campaign_id: UUID,
    experiment_id: UUID,
    medoids: set[UUID],
) -> None:
    spec = json.loads(_OPENAPI.read_text(encoding="utf-8"))
    ids = {
        "campaign_id": campaign_id,
        "experiment_id": experiment_id,
        "run_id": UUID(_web_fixture("run_detail")["id"]),
    }
    assert ids["run_id"] in medoids

    page = _web_fixture("runs_page")
    risk = _web_fixture("risk_slice")
    routes: tuple[tuple[str, str, dict[str, str | int]], ...] = (
        ("campaigns", "/api/v1/campaigns", {}),
        ("runs_page", "/api/v1/campaigns/{campaign_id}/runs", {"limit": len(page["items"])}),
        ("run_detail", "/api/v1/runs/{run_id}", {}),
        ("modes", "/api/v1/campaigns/{campaign_id}/modes", {}),
        ("importance", "/api/v1/campaigns/{campaign_id}/importance", {}),
        (
            "risk_slice",
            "/api/v1/campaigns/{campaign_id}/risk/slice",
            {
                "x": risk["x_param"],
                "y": risk["y_param"],
                "anchor": risk["anchor"],
                "resolution": risk["resolution"],
            },
        ),
        ("comparison", "/api/v1/experiments/{experiment_id}/comparison", {}),
    )
    for name, route, params in routes:
        response = client.get(route.format_map(ids), params=params)
        assert response.status_code == HTTPStatus.OK, response.text
        body = response.json()
        response_schema = spec["paths"][route]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        Draft202012Validator(
            {**response_schema, "components": spec["components"]},
            format_checker=FormatChecker(),
        ).validate(body)
        assert body == _web_fixture(name), f"{name}.json differs from the restored seed API"

    resolution = risk["resolution"]
    probabilities = risk["grid"]["p_fail"]
    assert len(probabilities) == resolution
    assert all(len(row) == resolution for row in probabilities)
    assert _web_fixture("importance")["importance"]
    assert _web_fixture("comparison")["strategies"]


def test_seed_fixture_restores_and_matches_openapi(seed_database_url: str, tmp_path: Path) -> None:
    """Restore committed data and verify that the dashboard routes serve it."""
    artifact_root = tmp_path / "artefacts"
    settings = load_settings(
        {
            "database.url": seed_database_url,
            "storage.artifact_root": str(artifact_root),
            "storage.workdir_root": str(tmp_path / "work"),
            "api.host": "127.0.0.1",
            "api.base_path": "/api/v1",
            "api.token": None,
            "observability.metrics_enabled": False,
        }
    )
    upgrade_head(settings)

    started = perf_counter()
    load_seed(seed_database_url, artifact_root)
    elapsed = perf_counter() - started
    assert elapsed < _MAX_RESTORE_SECONDS, f"seed restore took {elapsed:.2f}s"

    campaign_id, experiment_id, medoids = _verify_database(seed_database_url, artifact_root)
    app = create_app(settings)
    app.state.event_hub_autostart = False
    with TestClient(app) as client:
        _check_api(client, campaign_id=campaign_id, experiment_id=experiment_id, medoids=medoids)
