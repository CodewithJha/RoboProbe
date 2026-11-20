"""M3 exit: 100-run S-RANDOM kinematic2d campaign (T-049)."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import Engine, text
from typer.testing import CliRunner

from roboprobe.bootstrap import build_cli_services
from roboprobe.cli.main import ExitCode, app
from roboprobe.core.settings import load_settings
from roboprobe.core.types import RunStatus, Verdict
from roboprobe.store.orm import Base

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]
runner = CliRunner()
BUDGET = 100


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


@pytest.mark.timeout(180)
def test_k2d_random_100_inline(db_url: str) -> None:
    del db_url
    cfg = REPO / "configs" / "campaigns" / "k2d_random_100.yaml"
    result = runner.invoke(
        app,
        ["--json", "campaign", "run", str(cfg), "--inline", "--workers", "4"],
    )
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "COMPLETED"
    assert payload["runs"] == BUDGET

    cid = UUID(payload["campaign_id"])
    settings = load_settings()
    services = build_cli_services(settings)
    try:
        with services.make_uow() as uow:
            runs: list[object] = []
            cursor = None
            while True:
                page = uow.runs.list_for_campaign(cid, limit=None, cursor=cursor)
                runs.extend(page.items)
                cursor = page.next_cursor
                if cursor is None:
                    break
            assert len(runs) == BUDGET
            ordinals = [r.ordinal for r in runs]
            assert len(set(ordinals)) == BUDGET
            assert all(
                RunStatus(str(getattr(r.status, "value", r.status))) is RunStatus.DONE for r in runs
            )
            verdicts = [
                Verdict(str(getattr(r.verdict, "value", r.verdict)))
                for r in runs
                if r.verdict is not None
            ]
            assert Verdict.PASS in verdicts
            for run in runs:
                arts = uow.artifacts.list_for_run(run.id)
                traces = [a for a in arts if a.kind == "trace"]
                manifests = [a for a in arts if a.kind == "manifest"]
                assert len(traces) == 1
                assert traces[0].sha256
                assert len(manifests) == 1
                assert run.manifest is not None
    finally:
        services.close()
