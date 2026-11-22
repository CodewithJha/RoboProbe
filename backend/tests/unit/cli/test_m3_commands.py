"""CliRunner coverage for M3 CLI groups. Fast: all I/O stubbed."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import yaml
from tests.fakes.store import InMemoryUnitOfWork, _Runs
from typer.testing import CliRunner

from roboprobe.cli.main import ExitCode, app
from roboprobe.core.types import CampaignStatus, RunOutcome, RunStatus, Verdict
from roboprobe.oracles.reevaluate import ReevaluateDiff
from roboprobe.runner.lifecycle import CampaignService
from roboprobe.runner.replay import ReplayAgreement
from roboprobe.scenario.regression import export_regression
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.store.records import (
    ArtifactRecord,
    CampaignRecord,
    NewRun,
    SpaceRecord,
    SutProfileRecord,
)

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[4]
WAREHOUSE = REPO / "configs" / "scenario_spaces" / "warehouse_v1.yaml"
_SPACE_VERSION = "09cf763f2e0d"

runner = CliRunner()


def _fake_services(uow: InMemoryUnitOfWork | None = None) -> SimpleNamespace:
    mem = uow or InMemoryUnitOfWork()

    def factory() -> InMemoryUnitOfWork:
        return mem

    return SimpleNamespace(
        settings=SimpleNamespace(
            storage=SimpleNamespace(artifact_root=Path("artifacts")),
            runner=SimpleNamespace(tick_interval_s=0.01, heartbeat_timeout_s=30.0),
        ),
        infra=SimpleNamespace(uow_factory=factory, queue=SimpleNamespace(), engine=object()),
        campaigns=CampaignService(factory),
        uow_factory=factory,
        make_uow=factory,
        close=lambda: None,
    )


def _seed_campaign(
    uow: InMemoryUnitOfWork,
    *,
    status: CampaignStatus = CampaignStatus.CREATED,
) -> UUID:
    cid = uuid4()
    with uow:
        uow.spaces.add(
            SpaceRecord(
                id="warehouse_v1",
                version=_SPACE_VERSION,
                name="wh",
                definition={},
            )
        )
        uow.sut_profiles.add(
            SutProfileRecord(
                id="k2d_default",
                backend="kinematic2d",
                config={},
                config_hash="c" * 16,
            )
        )
        uow.campaigns.add(
            CampaignRecord(
                id=cid,
                name="c",
                space_id="warehouse_v1",
                space_version=_SPACE_VERSION,
                sut_profile_id="k2d_default",
                backend="kinematic2d",
                strategy_id="S-RANDOM",
                seed=1,
                budget=10,
                oracle_config={},
                status=status,
            )
        )
        uow.commit()
    return cid


def _seed_done_run(uow: InMemoryUnitOfWork) -> UUID:
    cid = _seed_campaign(uow, status=CampaignStatus.RUNNING)
    with uow:
        (rid,) = uow.runs.insert_batch(
            [
                NewRun(
                    campaign_id=cid,
                    ordinal=0,
                    backend="kinematic2d",
                    scenario_hash="a" * 16,
                    scenario_values={},
                    x_unit=(0.1,),
                    seed=1,
                    phase="baseline",
                )
            ]
        )
        row = uow.runs.get(rid)
        assert row is not None
        uow.runs._db.runs[rid] = row.model_copy(
            update={
                "status": RunStatus.DONE,
                "verdict": Verdict.PASS,
                "robustness": 1.0,
            }
        )
        uow.artifacts.add(
            ArtifactRecord(
                id=uuid4(),
                run_id=rid,
                campaign_id=cid,
                kind="trace",
                rel_path="trace/run.parquet",
                sha256="deadbeef",
                size_bytes=4,
                media_type="application/octet-stream",
            )
        )
        uow.commit()
    return rid


@pytest.fixture
def cli_services(monkeypatch: pytest.MonkeyPatch) -> InMemoryUnitOfWork:
    uow = InMemoryUnitOfWork()
    fake = _fake_services(uow)
    for mod in (
        "roboprobe.cli.space",
        "roboprobe.cli.campaign",
        "roboprobe.cli.runs",
        "roboprobe.cli.oracle",
        "roboprobe.cli.replay",
        "roboprobe.cli.scenario",
        "roboprobe.cli.run",
    ):
        monkeypatch.setattr(f"{mod}.build_cli_services", lambda _s, f=fake: f)
    return uow


def test_db_upgrade(monkeypatch: pytest.MonkeyPatch, settings_env: Path) -> None:
    calls: list[object] = []

    def _upgrade(settings: object) -> None:
        calls.append(settings)

    monkeypatch.setattr("roboprobe.cli.db.upgrade_head", _upgrade)
    result = runner.invoke(app, ["--json", "db", "upgrade"])
    assert result.exit_code == ExitCode.OK, result.output
    assert json.loads(result.stdout)["revision"] == "head"
    assert calls


def test_space_validate(settings_env: Path) -> None:
    result = runner.invoke(app, ["--json", "space", "validate", str(WAREHOUSE)])
    assert result.exit_code == ExitCode.OK, result.output
    assert json.loads(result.stdout)["id"] == "warehouse_v1"


def test_space_upgrade_schema_v1(settings_env: Path, tmp_path: Path) -> None:
    doc = yaml.safe_load(WAREHOUSE.read_text(encoding="utf-8"))
    path = tmp_path / "space.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    result = runner.invoke(app, ["--json", "space", "upgrade", str(path)])
    assert result.exit_code == ExitCode.OK, result.output
    assert json.loads(result.stdout)["schema_version"] == 1


def test_space_upgrade_rejects_unknown_schema(settings_env: Path, tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump({"schema_version": 99}), encoding="utf-8")
    result = runner.invoke(app, ["space", "upgrade", str(path)])
    assert result.exit_code in {ExitCode.RUNTIME_ERROR, ExitCode.USAGE_ERROR}


def test_space_list(cli_services: InMemoryUnitOfWork, settings_env: Path) -> None:
    with cli_services:
        cli_services.spaces.add(
            SpaceRecord(
                id="warehouse_v1",
                version=_SPACE_VERSION,
                name="Warehouse",
                definition={},
            )
        )
        cli_services.commit()
    result = runner.invoke(app, ["space", "list"])
    assert result.exit_code == ExitCode.OK
    assert "warehouse_v1" in result.output


def test_campaign_lifecycle(cli_services: InMemoryUnitOfWork, settings_env: Path) -> None:
    sid = str(_seed_campaign(cli_services))
    for cmd in ("start", "pause", "resume", "cancel"):
        result = runner.invoke(app, ["--json", "campaign", cmd, sid])
        assert result.exit_code == ExitCode.OK, result.output


def test_campaign_create_from_flags(
    monkeypatch: pytest.MonkeyPatch,
    settings_env: Path,
    cli_services: InMemoryUnitOfWork,
) -> None:
    cid = _seed_campaign(cli_services)
    monkeypatch.setattr(
        "roboprobe.cli.campaign.create_campaign_from_config",
        lambda *_a, **_k: cid,
    )
    result = runner.invoke(
        app,
        ["--json", "campaign", "create", "--space", "warehouse_v1", "--budget", "5"],
    )
    assert result.exit_code == ExitCode.OK, result.output
    assert json.loads(result.stdout)["campaign_id"] == str(cid)


def test_campaign_create_accepts_wizard_default_yaml(
    monkeypatch: pytest.MonkeyPatch,
    settings_env: Path,
    cli_services: InMemoryUnitOfWork,
) -> None:
    source = REPO / "backend/tests/fixtures/campaigns/wizard-default.yaml"
    monkeypatch.setattr("roboprobe.cli.campaign.register_space", lambda *_a, **_k: None)
    _seed_campaign(cli_services)
    result = runner.invoke(app, ["--json", "campaign", "create", "-f", str(source)])
    assert result.exit_code == ExitCode.OK, result.output
    created = cli_services.campaigns.get(UUID(json.loads(result.stdout)["campaign_id"]))
    assert created is not None
    config = yaml.safe_load(source.read_text(encoding="utf-8"))
    assert created.backend == config["backend"]
    assert created.space_version == config["space"]["version"]
    assert created.sut_profile_id == config["sut_profile_id"]
    assert created.seed == config["strategy"]["seed"]
    assert created.budget == config["budget"]
    assert created.batch_size == config["batch_size"]
    assert created.status == CampaignStatus.RUNNING


def test_campaign_status(cli_services: InMemoryUnitOfWork, settings_env: Path) -> None:
    cid = _seed_campaign(cli_services, status=CampaignStatus.RUNNING)
    result = runner.invoke(app, ["--json", "campaign", "status", str(cid)])
    assert result.exit_code == ExitCode.OK, result.output
    assert json.loads(result.stdout)["status"] == "RUNNING"


def test_runs_requeue_stuck(monkeypatch: pytest.MonkeyPatch, settings_env: Path) -> None:
    orch = SimpleNamespace(reaper=SimpleNamespace(reap=lambda: 3), close=lambda: None)
    monkeypatch.setattr("roboprobe.cli.runs.build_orchestrator", lambda _s: orch)
    bad = runner.invoke(app, ["runs", "requeue"])
    assert bad.exit_code == ExitCode.USAGE_ERROR
    ok = runner.invoke(app, ["--json", "runs", "requeue", "--stuck"])
    assert ok.exit_code == ExitCode.OK, ok.output
    assert json.loads(ok.stdout)["requeued_or_failed"] == 3


def test_queue_stats(cli_services: InMemoryUnitOfWork, settings_env: Path) -> None:
    _seed_campaign(cli_services, status=CampaignStatus.RUNNING)
    result = runner.invoke(app, ["queue", "stats"])
    assert result.exit_code == ExitCode.OK, result.output


def test_oracle_reevaluate(
    monkeypatch: pytest.MonkeyPatch,
    cli_services: InMemoryUnitOfWork,
    settings_env: Path,
    tmp_path: Path,
) -> None:
    rid = _seed_done_run(cli_services)
    monkeypatch.setattr(
        "roboprobe.cli.oracle.ScenarioSpace.from_yaml",
        lambda *_a, **_k: SimpleNamespace(task=object()),
    )
    diff = ReevaluateDiff(
        run_id=rid,
        stored_verdict="PASS",
        stored_robustness=1.0,
        new_outcome=RunOutcome(
            verdict=Verdict.PASS,
            robustness=1.0,
            primary_failure=None,
            metrics={},
            oracle_results=(),
        ),
        changed=False,
        oracle_set_version="0",
    )
    monkeypatch.setattr("roboprobe.cli.oracle.reevaluate_run", lambda *_a, **_k: diff)
    (tmp_path / "artifacts" / "trace").mkdir(parents=True)
    monkeypatch.setenv("ROBOPROBE_STORAGE__ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    result = runner.invoke(app, ["--json", "oracle", "reevaluate", str(rid)])
    assert result.exit_code == ExitCode.OK, result.output
    assert json.loads(result.stdout)["changed"] is False


def test_replay_cmd(
    monkeypatch: pytest.MonkeyPatch,
    cli_services: InMemoryUnitOfWork,
    settings_env: Path,
) -> None:
    rid = _seed_done_run(cli_services)
    replay_id = uuid4()
    monkeypatch.setattr(
        "roboprobe.cli.replay.enqueue_replays",
        lambda *_a, **_k: (replay_id,),
    )
    monkeypatch.setattr(
        "roboprobe.cli.replay.summarise_agreement",
        lambda *_a, **_k: ReplayAgreement(
            source_run_id=rid,
            replay_ids=(replay_id,),
            source_verdict="PASS",
            source_failure=None,
            agreements=1,
            disagreements=0,
            trace_matches=None,
            rows=(),
        ),
    )
    monkeypatch.setattr(
        "roboprobe.cli.replay.build_worker",
        lambda *_a, **_k: SimpleNamespace(claim=lambda: None, execute=lambda _c: None),
    )
    times = iter([0.0, 1000.0])
    monkeypatch.setattr("roboprobe.cli.replay.time.monotonic", lambda: next(times, 1000.0))
    result = runner.invoke(app, ["--json", "replay", str(rid)])
    assert result.exit_code == ExitCode.OK, result.output
    assert "source_run_id" in json.loads(result.stdout)


def test_scenario_export(
    cli_services: InMemoryUnitOfWork,
    settings_env: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(REPO)
    values = {
        "robot.max_speed": 0.44,
        "obstacle.clearance": 0.31,
        "env.illuminance": 12.5,
        "sensor.lidar_noise_std": 0.062,
        "env.floor_friction": 0.72,
        "comms.cmd_delay_ms": 140,
    }
    space = ScenarioSpace.from_yaml(WAREHOUSE, base_dir=REPO)
    scenario = space.make_scenario(values)
    rid = _seed_done_run(cli_services)
    with cli_services:
        row = cli_services.runs.get(rid)
        assert row is not None
        cli_services.runs._db.runs[rid] = row.model_copy(
            update={
                "scenario_values": dict(values),
                "scenario_hash": scenario.scenario_hash,
            }
        )
        cli_services.commit()
    out = tmp_path / "out.yaml"
    result = runner.invoke(app, ["--json", "scenario", "export", str(rid), "-o", str(out)])
    assert result.exit_code == ExitCode.OK, result.output
    assert out.is_file()


def test_orchestrator_service(monkeypatch: pytest.MonkeyPatch, settings_env: Path) -> None:
    class _Orch:
        def serve_forever(self, external: object | None = None) -> None:
            del external

        def request_stop(self) -> None: ...

    services = SimpleNamespace(
        settings=SimpleNamespace(
            worker=SimpleNamespace(health_host="127.0.0.1", health_port=0),
        ),
        uow_factory=InMemoryUnitOfWork,
        clock=SimpleNamespace(),
        metrics=SimpleNamespace(enabled=False),
        campaigns=SimpleNamespace(),
        reaper=SimpleNamespace(),
        scheduler=SimpleNamespace(),
        infra=SimpleNamespace(engine=object()),
        close=lambda: None,
    )
    monkeypatch.setattr("roboprobe.cli.services.build_orchestrator", lambda _s: services)
    monkeypatch.setattr("roboprobe.cli.services.Orchestrator", lambda **_kw: _Orch())
    result = runner.invoke(app, ["--json", "orchestrator"])
    assert result.exit_code == ExitCode.OK


def test_worker_service(monkeypatch: pytest.MonkeyPatch, settings_env: Path) -> None:
    class _Worker:
        def serve_forever(self, stop: object) -> None:
            del stop

        def request_stop(self) -> None: ...

    monkeypatch.setattr(
        "roboprobe.cli.services.ScenarioSpace.from_yaml",
        lambda *_a, **_k: SimpleNamespace(task=object()),
    )
    monkeypatch.setattr("roboprobe.cli.services.build_worker", lambda *_a, **_k: _Worker())
    result = runner.invoke(
        app, ["--json", "worker", "--backend", "kinematic2d", "--concurrency", "1"]
    )
    assert result.exit_code == ExitCode.OK, result.output


def test_api_service_starts(monkeypatch: pytest.MonkeyPatch, settings_env: Path) -> None:
    calls: list[tuple[object, ...]] = []

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "uvicorn":
            return SimpleNamespace(run=lambda *a, **k: calls.append(("run", a, k)))
        if name == "roboprobe.bootstrap.api":
            return SimpleNamespace(create_api_app=lambda _s: "app")
        return importlib.import_module(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("roboprobe.cli.services.importlib.import_module", fake_import)
    result = runner.invoke(app, ["api"])
    assert result.exit_code == ExitCode.OK, result.output
    assert calls and calls[0][0] == "run"


def test_artifacts_verify(monkeypatch: pytest.MonkeyPatch, settings_env: Path) -> None:
    monkeypatch.setattr(
        "roboprobe.cli.artifacts._artifacts_mod",
        lambda: SimpleNamespace(LocalArtifactStore=lambda *_a, **_k: object()),
    )
    monkeypatch.setattr(
        "roboprobe.cli.artifacts._store_mod",
        lambda: SimpleNamespace(verify=lambda _s: []),
    )
    result = runner.invoke(app, ["--json", "artifacts", "verify"])
    assert result.exit_code == ExitCode.OK, result.output
    assert json.loads(result.stdout)["ok"] is True


def test_gc_dry_run(monkeypatch: pytest.MonkeyPatch, settings_env: Path) -> None:
    report = SimpleNamespace(dry_run=True, orphans=[], retained_bags_deleted=[])

    monkeypatch.setattr(
        "roboprobe.cli.artifacts._artifacts_mod",
        lambda: SimpleNamespace(LocalArtifactStore=lambda *_a, **_k: object()),
    )
    monkeypatch.setattr(
        "roboprobe.cli.artifacts._store_mod",
        lambda: SimpleNamespace(gc=lambda *_a, **_k: report),
    )
    monkeypatch.setattr(
        "roboprobe.cli.artifacts._engine_mod",
        lambda: SimpleNamespace(
            create_engine_from_settings=lambda _d: SimpleNamespace(dispose=lambda: None),
            session_factory=lambda _e: object(),
        ),
    )
    monkeypatch.setattr(
        "roboprobe.cli.artifacts._uow_mod",
        lambda: SimpleNamespace(SqlAlchemyUnitOfWork=object),
    )
    result = runner.invoke(app, ["--json", "gc", "--dry-run"])
    assert result.exit_code == ExitCode.OK, result.output
    assert json.loads(result.stdout)["dry_run"] is True


def test_run_scenario(
    monkeypatch: pytest.MonkeyPatch,
    settings_env: Path,
    tmp_path: Path,
    cli_services: InMemoryUnitOfWork,
) -> None:
    space = ScenarioSpace.from_yaml(WAREHOUSE, base_dir=REPO)
    scenario = space.make_scenario(
        {
            "robot.max_speed": 0.44,
            "obstacle.clearance": 0.31,
            "env.illuminance": 12.5,
            "sensor.lidar_noise_std": 0.062,
            "env.floor_friction": 0.72,
            "comms.cmd_delay_ms": 140,
        }
    )
    reg_path = tmp_path / "reg.yaml"
    reg_path.write_text(
        export_regression(scenario, seed=42, provenance=None, expect=None),
        encoding="utf-8",
    )
    cid = uuid4()
    monkeypatch.chdir(REPO)
    monkeypatch.setattr("roboprobe.cli.run.create_campaign_from_config", lambda *_a, **_k: cid)

    orig_insert = _Runs.insert_batch

    def _insert_done(self: _Runs, runs: list[NewRun]) -> tuple[UUID, ...]:
        ids = orig_insert(self, runs)
        for rid in ids:
            row = self.get(rid)
            if row is not None:
                self._db.runs[rid] = row.model_copy(
                    update={
                        "status": RunStatus.DONE,
                        "verdict": Verdict.PASS,
                        "robustness": 1.0,
                    }
                )
        return ids

    monkeypatch.setattr(_Runs, "insert_batch", _insert_done)
    monkeypatch.setattr(
        "roboprobe.cli.run.build_worker",
        lambda *_a, **_k: SimpleNamespace(claim=lambda: None, execute=lambda _c: None),
    )
    monkeypatch.setenv("ROBOPROBE_STORAGE__WORKDIR_ROOT", str(tmp_path / "work"))
    monkeypatch.setenv(
        "ROBOPROBE_BACKENDS__KINEMATIC2D__MODEL_FILE",
        str(REPO / "configs" / "backends" / "kinematic2d_v1.yaml"),
    )
    result = runner.invoke(
        app, ["--json", "run", "--scenario", str(reg_path), "--backend", "kinematic2d"]
    )
    assert result.exit_code == ExitCode.OK, result.output
    body = json.loads(result.stdout)
    assert body["verdict"] == "PASS"
    assert body["campaign_id"] == str(cid)
