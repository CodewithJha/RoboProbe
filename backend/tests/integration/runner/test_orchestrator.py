"""Orchestrator supervisor (T-048)."""

from __future__ import annotations

import json
import socket
import sys
import time
import urllib.request
from pathlib import Path
from uuid import UUID

import pytest
import yaml
from sqlalchemy import Engine, text

from roboprobe.bootstrap import build_cli_services, build_orchestrator, build_worker
from roboprobe.cli.campaign import create_campaign_from_config
from roboprobe.cli.db import upgrade_head
from roboprobe.cli.space import REPO_ROOT
from roboprobe.core.health import Check, serve_health
from roboprobe.core.logging import configure_logging
from roboprobe.core.settings import load_settings
from roboprobe.core.types import RunStatus
from roboprobe.runner.orchestrator import Orchestrator
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.store.orm import Base

pytestmark = pytest.mark.integration


@pytest.fixture
def settings(pg_engine: Engine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    url = pg_engine.url.render_as_string(hide_password=False)
    monkeypatch.setenv("ROBOPROBE_DATABASE__URL", url)
    monkeypatch.setenv("ROBOPROBE_STORAGE__WORKDIR_ROOT", str(tmp_path / "w"))
    monkeypatch.setenv("ROBOPROBE_STORAGE__ARTIFACT_ROOT", str(tmp_path / "a"))
    monkeypatch.setenv("ROBOPROBE_OBSERVABILITY__METRICS_ENABLED", "true")
    monkeypatch.setenv("ROBOPROBE_RUNNER__TICK_INTERVAL_S", "0.05")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    health_port = int(sock.getsockname()[1])
    sock.close()
    monkeypatch.setenv("ROBOPROBE_WORKER__HEALTH_PORT", str(health_port))
    monkeypatch.setenv(
        "ROBOPROBE_BACKENDS__KINEMATIC2D__MODEL_FILE",
        str(REPO_ROOT / "configs" / "backends" / "kinematic2d_v1.yaml"),
    )
    monkeypatch.setenv(
        "ROBOPROBE_BACKENDS__GAZEBO_NAV2__PERCEPTION_MODEL_FILE",
        str(REPO_ROOT / "configs" / "perception" / "oakd_lowlight_v1.yaml"),
    )
    monkeypatch.chdir(REPO_ROOT)
    with pg_engine.begin() as conn:
        Base.metadata.drop_all(conn)
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    settings = load_settings()
    # Reset structlog onto a live stream (CliRunner can leave a closed capture).
    configure_logging(settings.logging, "test-orchestrator", "0.0.0", stream=sys.stderr)
    upgrade_head(settings)
    return settings.model_copy(
        update={
            "worker": settings.worker.model_copy(
                update={"backend": "kinematic2d", "poll_interval_s": 0.05}
            ),
            "runner": settings.runner.model_copy(update={"tick_interval_s": 0.05}),
        }
    )


def test_orchestrator_picks_up_campaign_and_healthz(settings, tmp_path: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "name": "orch",
                "space": {"id": "warehouse_v1"},
                "sut_profile_id": "k2d_default",
                "backend": "kinematic2d",
                "strategy": {"id": "S-RANDOM", "seed": 2},
                "budget": 4,
                "batch_size": 2,
                "start": True,
            }
        ),
        encoding="utf-8",
    )
    cid = create_campaign_from_config(cfg, settings)

    space = ScenarioSpace.from_yaml(
        REPO_ROOT / "configs" / "scenario_spaces" / "warehouse_v1.yaml",
        base_dir=REPO_ROOT,
    )
    orch_services = build_orchestrator(settings)
    worker = build_worker(settings, task=space.task, infra=orch_services.infra)
    worker.ensure_registered()
    orch = Orchestrator(
        settings=orch_services.settings,
        uow_factory=orch_services.uow_factory,
        clock=orch_services.clock,
        metrics=orch_services.metrics,
        campaigns=orch_services.campaigns,
        reaper=orch_services.reaper,
        scheduler=orch_services.scheduler,
        engine=orch_services.infra.engine,
        space_root=REPO_ROOT,
    )
    orch._health = serve_health(
        settings.worker.health_host,
        settings.worker.health_port,
        [Check(name="tick", probe=orch._health_probe)],
        orch.metrics,
    )
    try:
        end = time.monotonic() + settings.runner.tick_interval_s * 40
        pending = 0
        while time.monotonic() < end:
            orch.tick()
            # Give campaign threads a moment to step.
            time.sleep(settings.runner.tick_interval_s)
            cli = build_cli_services(settings)
            try:
                with cli.make_uow() as uow:
                    campaign_id = cid if isinstance(cid, UUID) else UUID(str(cid))
                    page = uow.runs.list_for_campaign(campaign_id, limit=None)
                    pending = sum(
                        1
                        for r in page.items
                        if RunStatus(str(getattr(r.status, "value", r.status))) is RunStatus.PENDING
                    )
            finally:
                cli.close()
            if pending > 0 and orch.last_tick_at is not None:
                break
        assert pending > 0, "orchestrator did not enqueue runs within tick budget"
        assert orch.last_tick_at is not None
        assert orch._health is not None
        port = orch._health.port
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as resp:
            body = json.loads(resp.read().decode())
        assert body["healthy"] is True
    finally:
        orch.request_stop()
        orch._shutdown_campaigns()
        if orch._health is not None:
            orch._health.stop()
            orch._health = None
        worker = None
        orch_services.close()
