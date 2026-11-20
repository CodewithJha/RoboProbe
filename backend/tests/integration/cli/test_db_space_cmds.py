"""CliRunner + Postgres for ``db upgrade`` and ``space`` commands (T-045a)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import Engine, inspect, text
from typer.testing import CliRunner

from roboprobe.cli.main import ExitCode, app
from roboprobe.store.orm import Base

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[4]
SPACE_YAML = REPO / "configs" / "scenario_spaces" / "warehouse_v1.yaml"
runner = CliRunner()


@pytest.fixture
def db_url(pg_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> str:
    url = pg_engine.url.render_as_string(hide_password=False)
    monkeypatch.setenv("ROBOPROBE_DATABASE__URL", url)
    with pg_engine.begin() as conn:
        Base.metadata.drop_all(conn)
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    return url


def test_db_upgrade_creates_schema(db_url: str, pg_engine: Engine) -> None:
    del db_url
    result = runner.invoke(app, ["--json", "db", "upgrade"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["revision"] == "head"
    assert "runs" in inspect(pg_engine).get_table_names()


def test_space_validate_ok(db_url: str) -> None:
    del db_url
    result = runner.invoke(app, ["--json", "space", "validate", str(SPACE_YAML)])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["id"] == "warehouse_v1"
    assert payload["version"]


def test_space_validate_invalid_exits_2(db_url: str, tmp_path: Path) -> None:
    del db_url
    bad = tmp_path / "bad.yaml"
    bad.write_text("schema_version: 1\nid: x\n", encoding="utf-8")
    result = runner.invoke(app, ["space", "validate", str(bad)])
    assert result.exit_code == ExitCode.USAGE_ERROR
    assert "invalid" in result.output.lower() or "error" in result.output.lower()


def test_space_register_and_list(db_url: str, pg_engine: Engine) -> None:
    del pg_engine
    assert runner.invoke(app, ["db", "upgrade"]).exit_code == ExitCode.OK
    reg = runner.invoke(app, ["--json", "space", "register", str(SPACE_YAML)])
    assert reg.exit_code == ExitCode.OK, reg.output
    listed = runner.invoke(app, ["--json", "space", "list"])
    assert listed.exit_code == ExitCode.OK, listed.output
    rows = json.loads(listed.stdout)
    assert any(row["id"] == "warehouse_v1" for row in rows)
