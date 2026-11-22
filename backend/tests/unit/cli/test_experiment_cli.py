"""ExperimentRunner driven through the CLI's UnitOfWork writer (fast, in-memory)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import yaml
from tests.fakes.store import InMemoryUnitOfWork
from typer.testing import CliRunner

from roboprobe.bootstrap.experiments import SqlExperimentWriter
from roboprobe.cli.experiment import _resolve_key
from roboprobe.cli.main import ExitCode, app
from roboprobe.core.clock import FakeClock
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.settings.experiments import ExperimentSettings
from roboprobe.core.types import CampaignStatus, RunStatus, Verdict
from roboprobe.experiments.planner import ComparabilityKey, ExperimentDesign
from roboprobe.experiments.runner import ExperimentRunner
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.store.artifacts import LocalArtifactStore
from roboprobe.store.records import NewRun, SpaceRecord, SutProfileRecord

pytestmark = pytest.mark.unit

BRANIN = Path(__file__).resolve().parents[4] / "configs" / "scenario_spaces" / "branin_2d.yaml"

KEY = ComparabilityKey(
    space_version="deadbeef0001",
    oracle_set_version="oracles-1",
    sut_config_hash="suthash00112233",
    backend_version="0.0.1",
    k2d_model_version="n/a",
)
SETTINGS = ExperimentSettings(default_seeds=2, max_concurrent_campaigns=1, bootstrap_resamples=16)


def _design() -> ExperimentDesign:
    return ExperimentDesign.model_validate(
        {
            "schema_version": 1,
            "id": "exp_unit",
            "backend": "benchmark",
            "space": {"id": "branin_2d", "version": KEY.space_version},
            "sut_profile_id": "bench",
            "strategies": [{"id": "S-RANDOM"}, {"id": "S-BO"}],
            "seeds": {"root": 3, "count": 2},
            "budget": 4,
            "metrics": ["MET-01", "MET-03"],
        }
    )


def _drive(uow: InMemoryUnitOfWork, campaign_id: UUID) -> CampaignStatus:
    runs = [
        NewRun(
            id=uuid4(),
            campaign_id=campaign_id,
            ordinal=i,
            backend="benchmark",
            scenario_hash="a" * 16,
            scenario_values={"x0": 0.1 * i, "x1": 0.2},
            x_unit=(0.1 * i, 0.2),
            seed=i,
            phase="select",
        )
        for i in range(4)
    ]
    with uow:
        uow.runs.insert_batch(runs)
        for i, run in enumerate(runs):
            row = uow.runs.get(run.id)
            assert row is not None
            uow.runs._db.runs[run.id] = row.model_copy(
                update={
                    "status": RunStatus.DONE,
                    "verdict": Verdict.FAIL if i % 2 else Verdict.PASS,
                    "robustness": 0.5 - i * 0.3,
                    "metrics": {"duration_s": 0.01} if i else {},
                }
            )
        uow.campaigns.set_status(campaign_id, CampaignStatus.COMPLETED)
        uow.commit()
    return CampaignStatus.COMPLETED


def _drive_isolated(
    uow: InMemoryUnitOfWork, campaign_id: UUID, settings: RoboProbeSettings, serve_probe: bool
) -> CampaignStatus:
    assert settings.worker.id_prefix.endswith(f":{campaign_id.hex}")
    assert not serve_probe
    return _drive(uow, campaign_id)


def test_uow_writer_runs_experiment_end_to_end_and_reports() -> None:
    uow = InMemoryUnitOfWork()
    writer = SqlExperimentWriter(lambda: uow)
    clock = FakeClock(start=datetime(2024, 1, 1, tzinfo=UTC))
    runner = ExperimentRunner(writer, SETTINGS, clock, lambda c: _drive(uow, c), new_uuid=uuid4)
    eid, comparison = runner.start(_design(), KEY)
    assert comparison["experiment_id"] == str(eid)
    assert set(comparison["strategies"]) == {"S-RANDOM", "S-BO"}
    stored = writer.get_experiment(eid)
    assert stored is not None
    assert len(writer.list_campaigns(eid)) == 4
    first = writer.list_campaigns(eid)[0]
    assert len(writer.campaign_runs(first.id)) == 4  # type: ignore[attr-defined]
    assert runner.report(eid)["experiment_id"] == str(eid)


def test_resolve_key_marks_k2d_model_only_for_kinematic_backend() -> None:
    space = type("S", (), {"version": "v1"})()
    assert _resolve_key(space, "h", "kinematic2d").k2d_model_version == "kinematic2d"
    assert _resolve_key(space, "h", "benchmark").k2d_model_version == "n/a"


def test_experiment_cli_run_then_report(
    monkeypatch: pytest.MonkeyPatch, settings_env: Path, tmp_path: Path
) -> None:
    uow = InMemoryUnitOfWork()
    mod = "roboprobe.cli.experiment"
    services = SimpleNamespace(
        make_uow=lambda: uow,
        uow_factory=lambda: uow,
        campaigns=SimpleNamespace(start=lambda _cid: None),
        infra=SimpleNamespace(artifact_store=LocalArtifactStore(tmp_path / "art"), engine=None),
        close=lambda: None,
    )
    for target in (mod, "roboprobe.cli.report", "roboprobe.cli.analyze"):
        monkeypatch.setattr(f"{target}.build_cli_services", lambda _s: services)
    monkeypatch.setattr(f"{mod}.register_space", lambda *_a, **_k: None)
    monkeypatch.setattr(
        f"{mod}.run_inline",
        lambda cid, settings, workers, serve_probe: _drive_isolated(
            uow, cid, settings, serve_probe
        ),
    )
    space = ScenarioSpace.from_yaml(BRANIN, base_dir=BRANIN.parents[2])
    design = tmp_path / "exp.yaml"
    body = _design().model_dump(mode="json", exclude_none=True)
    body["space"]["version"] = space.version
    body["sut_profile_id"] = "k2d_default"
    design.write_text(yaml.safe_dump(body), encoding="utf-8")

    raw = tmp_path / "raw.parquet"
    args = ["--json", "experiment", "run", str(design), "--raw-parquet", str(raw)]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == ExitCode.OK, result.output
    eid = json.loads(result.stdout)["experiment_id"]
    assert raw.is_file()
    with uow:
        assert uow.sut_profiles.get("k2d_default") is not None
    again = CliRunner().invoke(app, [*args[:4], "--resume", eid])
    assert again.exit_code == ExitCode.OK, again.output
    assert json.loads(again.stdout)["experiment_id"] == eid

    report = CliRunner().invoke(app, ["--json", "experiment", "report", eid])
    assert report.exit_code == ExitCode.OK, report.output
    assert json.loads(report.stdout)["experiment_id"] == eid
    table = CliRunner().invoke(app, ["experiment", "report", eid, "--table"])
    assert table.exit_code == ExitCode.OK, table.output
    assert "S-RANDOM" in table.stdout

    html = tmp_path / "exp.html"
    out = CliRunner().invoke(app, ["--json", "experiment", "report", eid, "-o", str(html)])
    assert out.exit_code == ExitCode.OK, out.output
    assert html.is_file()
    html2 = tmp_path / "exp2.html"
    rep = CliRunner().invoke(app, ["--json", "report", "-o", str(html2), eid])
    assert rep.exit_code == ExitCode.OK, rep.output
    assert json.loads(rep.stdout)["kind"] == "experiment"
    missing = CliRunner().invoke(app, ["--json", "report", "-o", str(html2), str(uuid4())])
    assert missing.exit_code != ExitCode.OK

    calls: list[str] = []

    class _Runner:
        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        def request(self, cid: UUID, kind: object) -> UUID:
            calls.append(f"request:{kind}")
            return cid

        def schedule(self, cid: UUID, kind: object, *, complete_campaign: bool) -> object:
            calls.append(f"schedule:{complete_campaign}")
            return None

    monkeypatch.setattr("roboprobe.cli.analyze.AnalysisJobRunner", _Runner)
    cid = str(uuid4())
    waited = CliRunner().invoke(app, ["--json", "analyze", "--wait", cid])
    assert waited.exit_code == ExitCode.OK, waited.output
    assert json.loads(waited.stdout)["waited"] is True
    queued = CliRunner().invoke(app, ["--json", "analyze", "--kind", "incremental", cid])
    assert queued.exit_code == ExitCode.OK, queued.output
    assert json.loads(queued.stdout)["scheduled"] is False
    assert len(calls) == 2


def test_bundle_cli_export_then_import_skip(
    monkeypatch: pytest.MonkeyPatch, settings_env: Path, tmp_path: Path
) -> None:
    uow = InMemoryUnitOfWork()
    writer = SqlExperimentWriter(lambda: uow)
    clock = FakeClock(start=datetime(2024, 1, 1, tzinfo=UTC))
    runner = ExperimentRunner(writer, SETTINGS, clock, lambda c: _drive(uow, c), new_uuid=uuid4)
    eid, _ = runner.start(_design(), KEY)
    disposed: list[bool] = []

    class _Engine:
        def dispose(self) -> None:
            disposed.append(True)

    engine_mod = SimpleNamespace(
        create_engine_from_settings=lambda _db: _Engine(),
        session_factory=lambda _engine: None,
    )
    uow_mod = SimpleNamespace(SqlAlchemyUnitOfWork=lambda _f, notify_channel: uow)
    monkeypatch.setattr("roboprobe.cli.bundle._engine_mod", lambda: engine_mod)
    monkeypatch.setattr("roboprobe.cli.bundle._uow_mod", lambda: uow_mod)
    with uow:
        camp = next(iter(uow.campaigns.list_for_experiment(eid)))
        uow.spaces.add(
            SpaceRecord(id=camp.space_id, version=camp.space_version, name="b", definition={})
        )
        uow.sut_profiles.add(
            SutProfileRecord(
                id=camp.sut_profile_id, backend=camp.backend, config={}, config_hash="h"
            )
        )
        uow.commit()
    tarball = tmp_path / "camp.tar.zst"
    exp = CliRunner().invoke(app, ["--json", "export", "-o", str(tarball), str(camp.id)])
    assert exp.exit_code == ExitCode.OK, exp.output
    assert tarball.is_file()
    imp = CliRunner().invoke(app, ["--json", "import", "--on-conflict", "skip", str(tarball)])
    assert imp.exit_code == ExitCode.OK, imp.output
    assert json.loads(imp.stdout)["campaign_id"] == str(camp.id)
    assert disposed == [True, True]
    services = SimpleNamespace(
        make_uow=lambda: uow,
        infra=SimpleNamespace(artifact_store=LocalArtifactStore(tmp_path / "art")),
        close=lambda: None,
    )
    monkeypatch.setattr("roboprobe.cli.report.build_cli_services", lambda _s: services)
    html = tmp_path / "camp.html"
    rep = CliRunner().invoke(app, ["--json", "report", "-o", str(html), str(camp.id)])
    assert rep.exit_code == ExitCode.OK, rep.output
    assert json.loads(rep.stdout)["kind"] == "campaign"
    assert html.is_file()
