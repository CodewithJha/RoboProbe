"""Export → run regression round-trip (T-045c)."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
import yaml
from sqlalchemy import Engine, text
from typer.testing import CliRunner

from roboprobe.bootstrap import build_cli_services
from roboprobe.cli.main import ExitCode, app
from roboprobe.core.settings import load_settings
from roboprobe.store.orm import Base

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[4]
runner = CliRunner()


@pytest.fixture
def db_url(pg_engine: Engine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    url = pg_engine.url.render_as_string(hide_password=False)
    monkeypatch.setenv("ROBOPROBE_DATABASE__URL", url)
    monkeypatch.setenv("ROBOPROBE_STORAGE__WORKDIR_ROOT", str(tmp_path / "w"))
    monkeypatch.setenv("ROBOPROBE_STORAGE__ARTIFACT_ROOT", str(tmp_path / "a"))
    monkeypatch.setenv("ROBOPROBE_OBSERVABILITY__METRICS_ENABLED", "false")
    monkeypatch.setenv(
        "ROBOPROBE_BACKENDS__KINEMATIC2D__MODEL_FILE",
        str(REPO / "configs" / "backends" / "kinematic2d_v1.yaml"),
    )
    monkeypatch.setenv(
        "ROBOPROBE_BACKENDS__GAZEBO_NAV2__PERCEPTION_MODEL_FILE",
        str(REPO / "configs" / "perception" / "oakd_lowlight_v1.yaml"),
    )
    monkeypatch.chdir(REPO)
    with pg_engine.begin() as conn:
        Base.metadata.drop_all(conn)
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    assert runner.invoke(app, ["db", "upgrade"]).exit_code == ExitCode.OK
    return url


def test_export_then_run_round_trip(db_url: str, tmp_path: Path) -> None:
    del db_url
    cfg = tmp_path / "src.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "name": "export-src",
                "space": {"id": "warehouse_v1"},
                "sut_profile_id": "k2d_default",
                "backend": "kinematic2d",
                "strategy": {"id": "S-RANDOM", "seed": 5},
                "budget": 1,
                "batch_size": 1,
                "start": True,
            }
        ),
        encoding="utf-8",
    )
    created = runner.invoke(
        app, ["--json", "campaign", "run", str(cfg), "--inline", "--workers", "1"]
    )
    assert created.exit_code == ExitCode.OK, created.output
    cid = UUID(json.loads(created.stdout)["campaign_id"])
    settings = load_settings()
    services = build_cli_services(settings)
    try:
        with services.make_uow() as uow:
            run_id = uow.runs.list_for_campaign(cid, limit=None).items[0].id
            verdict = uow.runs.get(run_id).verdict
    finally:
        services.close()

    out = tmp_path / "reg.yaml"
    exported = runner.invoke(app, ["--json", "scenario", "export", str(run_id), "-o", str(out)])
    assert exported.exit_code == ExitCode.OK, exported.output
    assert out.is_file()

    # Align expect with the source verdict so --fail-on-failure succeeds.
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    doc["expect"] = {"verdict": str(getattr(verdict, "value", verdict))}
    out.write_text(yaml.safe_dump(doc), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--json",
            "run",
            "--scenario",
            str(out),
            "--backend",
            "kinematic2d",
            "--fail-on-failure",
        ],
    )
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["verdict"] == doc["expect"]["verdict"]
    assert payload["expect"] == doc["expect"]["verdict"]
