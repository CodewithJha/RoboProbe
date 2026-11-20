"""WorkerProcess claim → execute pipeline (T-040a)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from tests.contract.test_backend_contract import FakeBackend
from tests.fakes.store import InMemoryRunQueue, InMemoryUnitOfWork

from roboprobe.core.clock import FakeClock
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.settings.oracles import OracleThresholds
from roboprobe.core.types import CampaignStatus, RunStatus, TaskSpec, Verdict
from roboprobe.oracles.goal import GoalOracle
from roboprobe.oracles.verdict import VerdictEngine
from roboprobe.runner.worker import WorkerProcess
from roboprobe.scenario.task import load_task
from roboprobe.store.artifacts import LocalArtifactStore
from roboprobe.store.records import CampaignRecord, NewRun, SpaceRecord, SutProfileRecord

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[4]


@pytest.fixture
def task() -> TaskSpec:
    return load_task(REPO / "tasks" / "warehouse_delivery_v1.yaml", strict=False)


def _settings(tmp_path: Path) -> RoboProbeSettings:
    return RoboProbeSettings(
        storage={"workdir_root": str(tmp_path / "work"), "artifact_root": str(tmp_path / "art")},
        worker={"backend": "fake", "id_prefix": "test", "poll_interval_s": 0.01},
    )


def _seed(uow: InMemoryUnitOfWork, settings: RoboProbeSettings) -> object:
    cid = uuid4()
    with uow:
        uow.sut_profiles.add(
            SutProfileRecord(id="sut", backend="fake", config={}, config_hash="c" * 16)
        )
        uow.spaces.add(SpaceRecord(id="s", version="v", name="n", definition={}))
        uow.campaigns.add(
            CampaignRecord(
                id=cid,
                name="c",
                space_id="s",
                space_version="v",
                sut_profile_id="sut",
                backend="fake",
                strategy_id="S-RANDOM",
                seed=1,
                budget=10,
                oracle_config={},
                status=CampaignStatus.RUNNING,
            )
        )
        uow.runs.insert_batch(
            [
                NewRun(
                    campaign_id=cid,
                    ordinal=0,
                    backend="fake",
                    scenario_hash="a" * 16,
                    scenario_values={"robot.max_speed": 0.5},
                    x_unit=(0.5,),
                    seed=7,
                    phase="baseline",
                )
            ]
        )
        uow.commit()
    return cid


def test_claimed_run_ends_done_with_verdict(tmp_path: Path, task: TaskSpec) -> None:
    settings = _settings(tmp_path)
    uow = InMemoryUnitOfWork()
    _seed(uow, settings)
    queue = InMemoryRunQueue(
        uow,
        wall_timeout_s=settings.worker.default_wall_timeout_s,
        sim_time_budget_s=settings.worker.default_sim_time_budget_s,
    )
    clock = FakeClock(
        start=__import__("datetime").datetime(2020, 1, 1, tzinfo=__import__("datetime").UTC)
    )
    store = LocalArtifactStore(settings.storage.artifact_root)
    engine = VerdictEngine([GoalOracle(OracleThresholds())])
    worker = WorkerProcess(
        backend=FakeBackend(settings),
        uow_factory=lambda: uow,
        queue=queue,
        artifact_store=store,
        verdict_engine=engine,
        clock=clock,
        worker_settings=settings.worker,
        storage_settings=settings.storage,
        task=task,
    )
    claimed = worker.claim()
    assert claimed is not None
    worker.execute(claimed)
    with uow:
        run = uow.runs.get(claimed.run_id)
        assert run is not None
        assert run.status is RunStatus.DONE
        assert run.verdict in {Verdict.PASS, Verdict.FAIL, Verdict.INVALID}


def test_backend_exception_maps_to_invalid(tmp_path: Path, task: TaskSpec) -> None:
    settings = _settings(tmp_path)
    uow = InMemoryUnitOfWork()
    _seed(uow, settings)
    queue = InMemoryRunQueue(
        uow,
        wall_timeout_s=settings.worker.default_wall_timeout_s,
        sim_time_budget_s=settings.worker.default_sim_time_budget_s,
    )

    class Boom(FakeBackend):
        def run_episode(self, req, materialized, on_progress=None):
            raise RuntimeError("boom")

    worker = WorkerProcess(
        backend=Boom(settings),
        uow_factory=lambda: uow,
        queue=queue,
        artifact_store=LocalArtifactStore(settings.storage.artifact_root),
        verdict_engine=VerdictEngine([GoalOracle(OracleThresholds())]),
        clock=FakeClock(
            start=__import__("datetime").datetime(2020, 1, 1, tzinfo=__import__("datetime").UTC)
        ),
        worker_settings=settings.worker,
        storage_settings=settings.storage,
        task=task,
    )
    claimed = worker.claim()
    assert claimed is not None
    worker.execute(claimed)
    with uow:
        run = uow.runs.get(claimed.run_id)
        assert run is not None
        assert run.status is RunStatus.ERROR
        assert run.verdict is Verdict.INVALID
        assert run.infra_error is not None and "infra_error" in run.infra_error
    # Worker continues: second claim returns None (queue empty).
    assert worker.claim() is None
