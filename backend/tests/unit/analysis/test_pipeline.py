"""Unit tests for :mod:`roboprobe.analysis.pipeline` (T-075a)."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import pytest
from tests.fakes.store import InMemoryUnitOfWork
from tests.unit.analysis.conftest import DEFAULT_METRICS, REPO_ROOT, WAREHOUSE

from roboprobe.analysis.base import AnalysisContext, AnalysisKind
from roboprobe.analysis.pipeline import analyze_campaign, default_analyzers
from roboprobe.core.clock import FakeClock
from roboprobe.core.errors import ValidationError
from roboprobe.core.metrics_registry import create_metrics
from roboprobe.core.settings.analysis import AnalysisSettings, RiskSettings
from roboprobe.core.types import CampaignStatus, RunStatus, Verdict
from roboprobe.scenario._documents import validate_document
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.store.records import CampaignRecord, NewRun, SpaceRecord, SutProfileRecord

pytestmark = pytest.mark.unit


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2025, 1, 1, tzinfo=UTC))


def _load_space(space_id: str, version: str) -> ScenarioSpace:
    space = ScenarioSpace.from_yaml(WAREHOUSE, base_dir=REPO_ROOT)
    assert space.id == space_id
    assert space.version == version
    return space


def _seed_campaign(uow: InMemoryUnitOfWork, space: ScenarioSpace) -> UUID:
    cid = uuid4()
    with uow:
        uow.spaces.add(
            SpaceRecord(
                id=space.id,
                version=space.version,
                name=space.name,
                definition={},
            )
        )
        uow.sut_profiles.add(
            SutProfileRecord(id="sut-k2d", backend="kinematic2d", config={}, config_hash="a" * 16)
        )
        uow.campaigns.add(
            CampaignRecord(
                id=cid,
                name="analysis-pipeline",
                space_id=space.id,
                space_version=space.version,
                sut_profile_id="sut-k2d",
                backend="kinematic2d",
                strategy_id="S-RANDOM",
                seed=7,
                budget=40,
                oracle_config={},
                status=CampaignStatus.RUNNING,
            )
        )
        runs = _synthetic_fail_runs(space)
        for ordinal, payload in enumerate(runs):
            (rid,) = uow.runs.insert_batch(
                [
                    NewRun(
                        campaign_id=cid,
                        ordinal=ordinal,
                        backend="kinematic2d",
                        scenario_hash=f"h{ordinal:02d}",
                        scenario_values=payload["values"],
                        x_unit=tuple(space.to_unit(payload["values"])),
                        seed=ordinal + 1,
                        phase="falsify",
                    )
                ]
            )
            row = uow.runs.get(rid)
            assert row is not None
            uow.runs._db.runs[rid] = row.model_copy(
                update={
                    "status": RunStatus.DONE,
                    "verdict": Verdict.FAIL,
                    "robustness": payload["robustness"],
                    "primary_failure": payload["primary"],
                    "metrics": dict(payload["metrics"]),
                }
            )
        uow.commit()
    return cid


def _synthetic_fail_runs(space: ScenarioSpace) -> list[dict[str, object]]:
    nominal = space.nominal_values()
    rng = np.random.Generator(np.random.PCG64(11))
    payloads: list[dict[str, object]] = []
    clusters = [(0.45, 10.0), (0.12, 800.0)]
    for speed, light in clusters:
        for _ in range(8):
            values = dict(nominal)
            values["robot.max_speed"] = float(np.clip(speed + rng.normal(0, 0.01), 0.1, 0.5))
            values["env.illuminance"] = float(np.clip(light + rng.normal(0, 1.0), 5.0, 1000.0))
            payloads.append(
                {
                    "values": values,
                    "robustness": -0.5 + rng.normal(0, 0.05),
                    "primary": "F-COL",
                    "metrics": dict(DEFAULT_METRICS),
                }
            )
    return payloads


def test_analyze_campaign_full(tmp_path: Path, space: ScenarioSpace, clock: FakeClock) -> None:
    uow = InMemoryUnitOfWork()
    cid = _seed_campaign(uow, space)
    arts = importlib.import_module("roboprobe.store.artifacts")
    store = arts.LocalArtifactStore(tmp_path / "arts")
    with uow:
        report = analyze_campaign(
            cid,
            uow,
            store,
            settings=AnalysisSettings(),
            risk=RiskSettings(slice_resolution=8, volume_samples=64),
            clock=clock,
            load_space=_load_space,
        )
        uow.commit()
    assert report.status in {"OK", "PARTIAL"}
    assert report.n_fail >= 12
    assert report.mode_codes
    validate_document(
        {
            "analysis_schema_version": report.analysis_schema_version,
            "analysis_id": str(report.analysis_id),
            "campaign_id": str(report.campaign_id),
            "kind": report.kind.value,
            "status": report.status,
            "n_runs": report.n_runs,
            "n_fail": report.n_fail,
            "mode_codes": report.mode_codes,
            "warnings": report.warnings,
            "summary": report.summary,
            "duration_s": report.duration_s,
        },
        schema="analysis_report",
        source="report",
    )
    assert "report.json" in report.artefact_sha256
    assert uow.analyses.get(report.analysis_id) is not None
    events = uow.events.since(0, campaign_id=cid)
    assert any(e.topic == "analysis.finished" for e in events)


def test_analyze_campaign_idempotent_mode_codes(
    space: ScenarioSpace, tmp_path: Path, clock: FakeClock
) -> None:
    uow = InMemoryUnitOfWork()
    cid = _seed_campaign(uow, space)
    arts = importlib.import_module("roboprobe.store.artifacts")
    store = arts.LocalArtifactStore(tmp_path / "arts")
    with uow:
        first = analyze_campaign(
            cid,
            uow,
            store,
            settings=AnalysisSettings(),
            clock=clock,
            load_space=_load_space,
        )
        second = analyze_campaign(
            cid,
            uow,
            store,
            settings=AnalysisSettings(),
            clock=clock,
            load_space=_load_space,
        )
        uow.commit()
    assert first.mode_codes
    assert first.mode_codes == second.mode_codes


def test_full_analysis_emits_fitted_gp_importance_ranks(
    space: ScenarioSpace, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _FittedGP:
        def __init__(self, dim: int, **_kwargs: object) -> None:
            self.lengthscales = np.arange(1, dim + 1, dtype=np.float64)

        def fit(self, _x: object, _y: object) -> None:
            pass

    def unavailable_mapper(*_args: object) -> None:
        msg = "risk grid unavailable"
        raise ValidationError(msg)

    monkeypatch.setattr("roboprobe.selection.surrogate.RobustnessGP", _FittedGP)
    monkeypatch.setattr("roboprobe.analysis.pipeline.RiskMapper", unavailable_mapper)
    uow = InMemoryUnitOfWork()
    cid = _seed_campaign(uow, space)
    store = importlib.import_module("roboprobe.store.artifacts").NullArtifactStore()
    with uow:
        rows = uow.runs.list_for_campaign(cid).items
        for row in rows[::2]:
            uow.runs._db.runs[row.id] = row.model_copy(
                update={"verdict": Verdict.PASS, "primary_failure": None, "robustness": 0.5}
            )
        report = analyze_campaign(
            cid,
            uow,
            store,
            settings=AnalysisSettings(),
            clock=clock,
            load_space=_load_space,
        )

    ranks = report.summary["importance"]["gp_normalized"]
    assert ranks is not None, report.warnings
    assert len(ranks) == space.dim
    assert ranks == sorted(ranks, reverse=True)


class _BoomAnalyzer:
    name = "boom"

    def run(self, ctx: AnalysisContext) -> None:
        del ctx
        msg = "optional step failed"
        raise RuntimeError(msg)


def test_optional_analyzer_failure_is_partial(
    space: ScenarioSpace, tmp_path: Path, clock: FakeClock
) -> None:
    uow = InMemoryUnitOfWork()
    cid = _seed_campaign(uow, space)
    arts = importlib.import_module("roboprobe.store.artifacts")
    store = arts.NullArtifactStore()
    steps = default_analyzers()
    analyzers = [*steps[:3], _BoomAnalyzer(), *steps[4:]]
    with uow:
        report = analyze_campaign(
            cid,
            uow,
            store,
            settings=AnalysisSettings(),
            clock=clock,
            load_space=_load_space,
            analyzers=analyzers,
        )
    assert report.status == "PARTIAL"
    assert any("boom" in w for w in report.warnings)


def test_tiny_plugin_analyzer_runs(space: ScenarioSpace, tmp_path: Path, clock: FakeClock) -> None:
    seen: dict[str, bool] = {}

    class _Plugin:
        name = "tiny"

        def run(self, ctx: AnalysisContext) -> None:
            seen["n"] = len(ctx.runs)

    uow = InMemoryUnitOfWork()
    cid = _seed_campaign(uow, space)
    arts = importlib.import_module("roboprobe.store.artifacts")
    store = arts.NullArtifactStore()
    with uow:
        report = analyze_campaign(
            cid,
            uow,
            store,
            settings=AnalysisSettings(),
            clock=clock,
            load_space=_load_space,
            analyzers=[*default_analyzers()[:3], _Plugin()],
            kind=AnalysisKind.INCREMENTAL,
        )
    assert seen["n"] > 0
    assert report.kind is AnalysisKind.INCREMENTAL


def test_metrics_observe_steps(space: ScenarioSpace, tmp_path: Path, clock: FakeClock) -> None:
    uow = InMemoryUnitOfWork()
    cid = _seed_campaign(uow, space)
    arts = importlib.import_module("roboprobe.store.artifacts")
    store = arts.NullArtifactStore()
    metrics = create_metrics(enabled=True)
    with uow:
        analyze_campaign(
            cid,
            uow,
            store,
            settings=AnalysisSettings(),
            clock=clock,
            metrics=metrics,
            load_space=_load_space,
        )
    expo = metrics.exposition().decode()
    assert "roboprobe_analysis_step_seconds" in expo
    assert 'step="features"' in expo
