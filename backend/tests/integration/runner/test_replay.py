"""Replay enqueue + k2d bit-identical agreement (T-044)."""

from __future__ import annotations

from pathlib import Path

import pytest

from roboprobe.backends.kinematic2d.backend import Kinematic2DBackend
from roboprobe.core.clock import SystemClock
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import CampaignStatus
from roboprobe.oracles.registry import create_all
from roboprobe.oracles.verdict import VerdictEngine
from roboprobe.runner.replay import ReplayRequest, enqueue_replays, summarise_agreement
from roboprobe.runner.worker import WorkerProcess
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.task import load_task
from roboprobe.store.artifacts import LocalArtifactStore
from roboprobe.store.ids import new_uuid
from roboprobe.store.queue_pg import PostgresRunQueue
from roboprobe.store.records import CampaignRecord, NewRun, SpaceRecord, SutProfileRecord

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[4]


def test_k2d_replay_same_seed_agrees(uow_factory, session_factory, tmp_path: Path) -> None:
    settings = RoboProbeSettings(
        storage={"workdir_root": str(tmp_path / "w"), "artifact_root": str(tmp_path / "a")},
        worker={"backend": "kinematic2d", "id_prefix": "rp", "poll_interval_s": 0.01},
        backends={
            "kinematic2d": {
                "model_file": str(REPO / "configs/backends/kinematic2d_v1.yaml"),
                "perception_model_file": str(REPO / "configs/perception/oakd_k2d_v1.yaml"),
            },
        },
        observability={"metrics_enabled": False},
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
                budget=10,
                oracle_config={},
                status=CampaignStatus.RUNNING,
            )
        )
        (source_id,) = uow.runs.insert_batch(
            [
                NewRun(
                    campaign_id=cid,
                    ordinal=0,
                    backend="kinematic2d",
                    scenario_hash=nominal.scenario_hash,
                    scenario_values=dict(nominal.values),
                    x_unit=x_unit,
                    seed=11,
                    phase="baseline",
                )
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
    claimed = worker.claim()
    assert claimed is not None
    worker.execute(claimed)

    ids = enqueue_replays(
        uow_factory, ReplayRequest(run_id=source_id, repeats=1, fresh_seeds=False)
    )
    assert len(ids) == 1
    claimed = worker.claim()
    assert claimed is not None
    worker.execute(claimed)

    with uow_factory() as uow:
        arts = {
            a.run_id: a.sha256 for a in uow.artifacts.list_for_run(source_id) if a.kind == "trace"
        }
        arts.update(
            {a.run_id: a.sha256 for a in uow.artifacts.list_for_run(ids[0]) if a.kind == "trace"}
        )
    summary = summarise_agreement(uow_factory, source_id, ids, trace_hashes=arts)
    assert summary.all_agree
    assert summary.trace_matches == 1
