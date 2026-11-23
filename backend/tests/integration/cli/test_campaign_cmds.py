"""Campaign CLI create / lifecycle / inline run (T-045b)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from sqlalchemy import Engine, text
from typer.testing import CliRunner

from roboprobe.cli.main import ExitCode, app
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


def test_campaign_create_start_status(db_url: str, tmp_path: Path) -> None:
    del db_url
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "name": "tiny",
                "space": {"id": "warehouse_v1"},
                "sut_profile_id": "k2d_default",
                "backend": "kinematic2d",
                "strategy": {"id": "S-RANDOM", "seed": 1},
                "budget": 4,
                "batch_size": 2,
            }
        ),
        encoding="utf-8",
    )
    created = runner.invoke(app, ["--json", "campaign", "create", "--config", str(cfg)])
    assert created.exit_code == ExitCode.OK, created.output
    cid = json.loads(created.stdout)["campaign_id"]
    started = runner.invoke(app, ["--json", "campaign", "start", cid])
    assert started.exit_code == ExitCode.OK, started.output
    assert json.loads(started.stdout)["status"] == "RUNNING"
    status = runner.invoke(app, ["--json", "campaign", "status", cid])
    assert status.exit_code == ExitCode.OK, status.output
    assert json.loads(status.stdout)["status"] == "RUNNING"


@pytest.mark.timeout(30)
@pytest.mark.parametrize("finite_grid", [False, True], ids=["random", "finite-grid"])
def test_campaign_run_inline_completes(
    db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, finite_grid: bool
) -> None:
    del db_url
    strategy, budget, backend, space, profile = (
        ("S-GRID", 5, "benchmark", "branin_2d", "benchmark_default")
        if finite_grid
        else ("S-RANDOM", 4, "kinematic2d", "warehouse_v1", "k2d_default")
    )
    if finite_grid:
        monkeypatch.setenv("ROBOPROBE_SELECTION__BENCHMARKS__FUNCTION", "branin_falsify")
    cfg = tmp_path / "inline.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "name": "inline4",
                "space": {"id": space},
                "sut_profile_id": profile,
                "backend": backend,
                "strategy": {"id": strategy, "seed": 3},
                "budget": budget,
                "batch_size": 2,
                "start": True,
            }
        ),
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["--json", "campaign", "run", str(cfg), "--inline", "--workers", "2"],
    )
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "COMPLETED"
    assert payload["runs"] == 4
