"""Experiment runner end-to-end on branin (T-102b; docs/14 §8, docs/12 §3.5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from tests.factories import make_observation
from tests.fakes.store import InMemoryUnitOfWork

from roboprobe.core.clock import FakeClock
from roboprobe.core.settings.experiments import ExperimentSettings
from roboprobe.core.types import CampaignStatus, JsonValue, RunStatus, Verdict
from roboprobe.experiments.planner import CampaignSpec, ComparabilityKey, ExperimentDesign
from roboprobe.experiments.runner import ExperimentRunner
from roboprobe.metrics.campaign_metrics import CampaignRun
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.selection.base import StrategyContext
from roboprobe.selection.benchmarks import branin_falsify
from roboprobe.selection.registry import create
from roboprobe.store.records import (
    CampaignRecord,
    ExperimentRecord,
    NewRun,
    SpaceRecord,
    SutProfileRecord,
)

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[4]
BRANIN = REPO / "configs" / "scenario_spaces" / "branin_2d.yaml"
KEY = ComparabilityKey(
    space_version="deadbeef0001",
    oracle_set_version="oracles-1",
    sut_config_hash="suthash00112233",
    backend_version="0.0.1",
    k2d_model_version="n/a",
)
# In-memory UoW is not thread-safe; keep concurrency at 1 for this harness.
SETTINGS = ExperimentSettings(default_seeds=3, max_concurrent_campaigns=1, bootstrap_resamples=64)


@dataclass
class _Writer:
    uow: InMemoryUnitOfWork
    clock: FakeClock
    drive_log: list[UUID] = field(default_factory=list)

    def add_experiment(self, *, name: str, design: dict[str, JsonValue], status: str) -> UUID:
        eid = uuid4()
        with self.uow:
            self.uow.experiments.add(
                ExperimentRecord(id=eid, name=name, design=design, status=status)
            )
            self.uow.commit()
        return eid

    def add_campaign(self, spec: CampaignSpec, experiment_id: UUID) -> UUID:
        cid = uuid4()
        with self.uow:
            self.uow.spaces.add(
                SpaceRecord(
                    id=spec.space_id,
                    version=spec.space_version,
                    name=spec.space_id,
                    definition={},
                )
            )
            self.uow.sut_profiles.add(
                SutProfileRecord(
                    id=spec.sut_profile_id or "bench",
                    backend=spec.backend,
                    config={},
                    config_hash=KEY.sut_config_hash,
                )
            )
            self.uow.campaigns.add(
                CampaignRecord(
                    id=cid,
                    name=spec.name,
                    space_id=spec.space_id,
                    space_version=spec.space_version,
                    sut_profile_id=spec.sut_profile_id or "bench",
                    backend=spec.backend,
                    strategy_id=spec.strategy_id,
                    strategy_params=dict(spec.strategy_params),
                    seed=spec.seed,
                    budget=spec.budget,
                    repeats=spec.repeats,
                    batch_size=spec.batch_size,
                    pins=dict(spec.pins),
                    oracle_config={},
                    stop_rules={},
                    status=CampaignStatus.CREATED,
                    experiment_id=experiment_id,
                    experiment_rep=spec.experiment_rep,
                    tags=spec.tags,
                )
            )
            self.uow.commit()
        return cid

    def get_experiment(self, experiment_id: UUID) -> object | None:
        with self.uow:
            return self.uow.experiments.get(experiment_id)

    def set_experiment_status(
        self, experiment_id: UUID, status: str, *, finished: bool = False
    ) -> None:
        with self.uow:
            self.uow.experiments.set_status(experiment_id, status)
            if finished:
                rec = self.uow.experiments.get(experiment_id)
                assert rec is not None
                self.uow.experiments.add(
                    rec.model_copy(update={"finished_at": self.clock.now(), "status": status})
                )
            self.uow.commit()

    def set_experiment_results(self, experiment_id: UUID, results: dict[str, JsonValue]) -> None:
        with self.uow:
            self.uow.experiments.set_results(experiment_id, results)
            self.uow.commit()

    def list_campaigns(self, experiment_id: UUID) -> list[object]:
        with self.uow:
            return list(self.uow.campaigns.list_for_experiment(experiment_id))

    def campaign_runs(self, campaign_id: UUID) -> list[CampaignRun]:
        with self.uow:
            page = self.uow.runs.list_for_campaign(campaign_id, limit=None)
            rows = sorted(page.items, key=lambda r: (r.ordinal, r.repeat_index))
        return [
            CampaignRun(
                verdict=r.verdict or Verdict.INVALID,
                wall_time_s=float(r.metrics.get("duration_s", 0.01)),
                x_unit=tuple(float(x) for x in r.x_unit),
                phase=str(r.phase or ""),
                tags=tuple(r.tags),
            )
            for r in rows
            if r.verdict is not None
        ]


def _design() -> ExperimentDesign:
    return ExperimentDesign.model_validate(
        {
            "schema_version": 1,
            "id": "exp_branin_smoke",
            "backend": "benchmark",
            "space": {"id": "branin_2d", "version": KEY.space_version},
            "sut_profile_id": "bench",
            "strategies": [{"id": "S-RANDOM"}, {"id": "S-BO"}],
            "seeds": {"root": 7, "count": 3},
            "budget": 30,
            "metrics": ["MET-01", "MET-03"],
        }
    )


def _drive_branin(uow: InMemoryUnitOfWork, campaign_id: UUID) -> CampaignStatus:
    space = ScenarioSpace.from_yaml(BRANIN, base_dir=REPO)
    with uow:
        camp = uow.campaigns.get(campaign_id)
        assert camp is not None
        uow.campaigns.set_status(campaign_id, CampaignStatus.RUNNING)
        uow.commit()
    ctx = StrategyContext(
        space=space,
        budget=camp.budget,
        seed=camp.seed,
        batch_size=4,
        params=dict(camp.strategy_params),
    )
    strat = create(camp.strategy_id, ctx)
    history = []
    new_runs: list[NewRun] = []
    verdicts: dict[UUID, tuple[Verdict, float]] = {}
    while len(history) < camp.budget:
        q = min(4, camp.budget - len(history))
        proposals = strat.propose(history, [], q)
        if not proposals:
            break
        for proposal in proposals:
            unit = space.to_unit(proposal.scenario.values)
            rho = branin_falsify(unit)
            verdict = Verdict.FAIL if rho < 0.0 else Verdict.PASS
            ordinal = len(history)
            run_id = uuid4()
            new_runs.append(
                NewRun(
                    id=run_id,
                    campaign_id=campaign_id,
                    ordinal=ordinal,
                    backend=camp.backend,
                    scenario_hash="a" * 16,
                    scenario_values={k: float(v) for k, v in proposal.scenario.values.items()},
                    x_unit=tuple(float(v) for v in unit),
                    seed=camp.seed + ordinal,
                    phase="select",
                )
            )
            verdicts[run_id] = (verdict, float(rho))
            history.append(
                make_observation(
                    x_unit=tuple(float(v) for v in unit),
                    robustness=float(rho),
                    verdict=verdict,
                    run_id=run_id,
                )
            )
            strat.observe(history[-1])
    with uow:
        uow.runs.insert_batch(new_runs)
        for run in new_runs:
            verdict, rho = verdicts[run.id]
            existing = uow.runs.get(run.id)
            assert existing is not None
            uow.runs._db.runs[run.id] = existing.model_copy(
                update={
                    "status": RunStatus.DONE,
                    "verdict": verdict,
                    "robustness": rho,
                    "metrics": {"duration_s": 0.01},
                }
            )
        uow.campaigns.set_status(campaign_id, CampaignStatus.COMPLETED)
        uow.commit()
    return CampaignStatus.COMPLETED


def test_branin_experiment_completes_and_stores_comparison(tmp_path: Path) -> None:
    uow = InMemoryUnitOfWork()
    clock = FakeClock(start=datetime(2024, 1, 1, tzinfo=UTC))
    writer = _Writer(uow, clock)
    driven: list[UUID] = []

    def drive(cid: UUID) -> CampaignStatus:
        driven.append(cid)
        return _drive_branin(uow, cid)

    runner = ExperimentRunner(writer, SETTINGS, clock, drive, new_uuid=uuid4)
    raw = tmp_path / "raw.parquet"
    eid, comparison = runner.start(_design(), KEY, raw_parquet=raw)
    assert len(driven) == 6
    assert comparison["experiment_id"] == str(eid)
    assert set(comparison["metrics"]) == {"MET-01", "MET-03"}
    assert set(comparison["strategies"]) == {"S-RANDOM", "S-BO"}
    for block in comparison["strategies"].values():
        assert isinstance(block, dict)
        assert "MET-03" in block
        assert "median" in block["MET-03"]
    assert raw.is_file()
    with uow:
        stored = uow.experiments.get(eid)
    assert stored is not None
    assert stored.status == "COMPLETED"
    assert stored.results is not None


def test_resume_skips_finished_campaigns() -> None:
    uow = InMemoryUnitOfWork()
    clock = FakeClock(start=datetime(2024, 1, 1, tzinfo=UTC))
    writer = _Writer(uow, clock)
    runner = ExperimentRunner(
        writer,
        SETTINGS,
        clock,
        drive=lambda cid: _drive_branin(uow, cid),
        new_uuid=uuid4,
    )
    eid, _ = runner.start(_design(), KEY)
    driven: list[UUID] = []

    def drive_again(cid: UUID) -> CampaignStatus:
        driven.append(cid)
        return _drive_branin(uow, cid)

    runner2 = ExperimentRunner(writer, SETTINGS, clock, drive_again, new_uuid=uuid4)
    runner2.start(_design(), KEY, experiment_id=eid)
    assert driven == []
