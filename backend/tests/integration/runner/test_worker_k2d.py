"""Worker + kinematic2d + Postgres integration (T-040a)."""

from __future__ import annotations

from pathlib import Path

import pytest

from roboprobe.backends.kinematic2d.backend import Kinematic2DBackend
from roboprobe.core.clock import SystemClock
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import CampaignStatus
from roboprobe.oracles.registry import create_all
from roboprobe.oracles.verdict import VerdictEngine
from roboprobe.runner.worker import WorkerProcess
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.task import load_task
from roboprobe.store.artifacts import LocalArtifactStore
from roboprobe.store.ids import new_uuid
from roboprobe.store.queue_pg import PostgresRunQueue
from roboprobe.store.records import CampaignRecord, NewRun, SpaceRecord, SutProfileRecord

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[4]


def test_worker_completes_twenty_k2d_runs(uow_factory, session_factory, tmp_path: Path) -> None:
    settings = RoboProbeSettings(
        storage={"workdir_root": str(tmp_path / "w"), "artifact_root": str(tmp_path / "a")},
        worker={"backend": "kinematic2d", "id_prefix": "k2d", "poll_interval_s": 0.01},
        backends={
            "kinematic2d": {
                "model_file": str(REPO / "configs/backends/kinematic2d_v1.yaml"),
                "perception_model_file": str(REPO / "configs/perception/oakd_k2d_v1.yaml"),
            },
        },
    )
    space = ScenarioSpace.from_yaml(
        REPO / "configs" / "scenario_spaces" / "warehouse_v1.yaml", base_dir=REPO
    )
    nominal = space.nominal()
    x_unit = tuple(float(x) for x in space.to_unit(nominal.values))
    cid = new_uuid()
    with uow_factory() as uow:
        uow.sut_profiles.add(
            SutProfileRecord(id="sut", backend="kinematic2d", config={}, config_hash="c" * 16)
        )
        uow.spaces.add(SpaceRecord(id=space.id, version=space.version, name="n", definition={}))
        uow.campaigns.add(
            CampaignRecord(
                id=cid,
                name="c",
                space_id=space.id,
                space_version=space.version,
                sut_profile_id="sut",
                backend="kinematic2d",
                strategy_id="S-RANDOM",
                seed=1,
                budget=20,
                oracle_config={},
                status=CampaignStatus.RUNNING,
            )
        )
        uow.runs.insert_batch(
            [
                NewRun(
                    campaign_id=cid,
                    ordinal=i,
                    backend="kinematic2d",
                    scenario_hash=nominal.scenario_hash,
                    scenario_values=dict(nominal.values),
                    x_unit=x_unit,
                    seed=i,
                    phase="baseline",
                )
                for i in range(20)
            ]
        )
        uow.commit()

    queue = PostgresRunQueue(
        session_factory,
        notify_channel="roboprobe_events",
        wall_timeout_s=120.0,
        sim_time_budget_s=60.0,
    )
    task = load_task(REPO / "tasks" / "warehouse_delivery_v1.yaml", strict=False)
    worker = WorkerProcess(
        backend=Kinematic2DBackend(settings),
        uow_factory=uow_factory,
        queue=queue,
        artifact_store=LocalArtifactStore(settings.storage.artifact_root),
        verdict_engine=VerdictEngine(create_all(settings.oracles)),
        clock=SystemClock(),
        worker_settings=settings.worker,
        storage_settings=settings.storage,
        task=task,
    )
    done = 0
    for _ in range(20):
        claimed = worker.claim()
        assert claimed is not None
        worker.execute(claimed)
        done += 1
    assert done == 20
    with uow_factory() as uow:
        page = uow.runs.list_for_campaign(cid, limit=50)
        assert sum(1 for r in page.items if r.status.value == "DONE") == 20
