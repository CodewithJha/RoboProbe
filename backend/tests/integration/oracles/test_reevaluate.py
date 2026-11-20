"""Offline oracle reevaluate (T-039b)."""

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


def _run_tiny_campaign(tmp_path: Path) -> UUID:
    cfg = tmp_path / "tiny.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "name": "reeval",
                "space": {"id": "warehouse_v1"},
                "sut_profile_id": "k2d_default",
                "backend": "kinematic2d",
                "strategy": {"id": "S-RANDOM", "seed": 7},
                "budget": 1,
                "batch_size": 1,
                "start": True,
            }
        ),
        encoding="utf-8",
    )
    result = runner.invoke(
        app, ["--json", "campaign", "run", str(cfg), "--inline", "--workers", "1"]
    )
    assert result.exit_code == ExitCode.OK, result.output
    cid = UUID(json.loads(result.stdout)["campaign_id"])
    settings = load_settings()
    services = build_cli_services(settings)
    try:
        with services.make_uow() as uow:
            page = uow.runs.list_for_campaign(cid, limit=None)
            assert page.items, "expected at least one run"
            return page.items[0].id
    finally:
        services.close()


def test_reevaluate_unchanged_matches(db_url: str, tmp_path: Path) -> None:
    del db_url
    run_id = _run_tiny_campaign(tmp_path)
    result = runner.invoke(app, ["--json", "oracle", "reevaluate", str(run_id)])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["changed"] is False
    assert payload["stored_verdict"] == payload["new_verdict"]
    assert payload["stored_robustness"] == payload["new_robustness"]


def test_reevaluate_threshold_override_can_change(db_url: str, tmp_path: Path) -> None:
    del db_url
    run_id = _run_tiny_campaign(tmp_path)
    thr = tmp_path / "thr.toml"
    # Raise goal.r_min so missed-goal robustness floors higher (more negative) than default.
    thr.write_text("[oracles.goal]\nr_min = 0.99\n", encoding="utf-8")
    baseline = runner.invoke(app, ["--json", "oracle", "reevaluate", str(run_id)])
    assert baseline.exit_code == ExitCode.OK, baseline.output
    overridden = runner.invoke(
        app, ["--json", "oracle", "reevaluate", str(run_id), "--thresholds", str(thr)]
    )
    assert overridden.exit_code == ExitCode.OK, overridden.output
    base = json.loads(baseline.stdout)
    over = json.loads(overridden.stdout)
    assert over["new_robustness"] != base["new_robustness"] or over["changed"] is True
