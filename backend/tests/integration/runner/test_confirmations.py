"""Integration: Casebook confirmation from enqueue through worker completion (T-110a)."""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from uuid import UUID

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from roboprobe.api.app import create_app
from roboprobe.bootstrap._infra import build_infrastructure
from roboprobe.bootstrap.worker import build_worker
from roboprobe.core.settings import RoboProbeSettings, load_settings
from roboprobe.core.settings.analysis import InteractionSettings
from roboprobe.core.types import CampaignStatus, FailureClass, RunStatus, Verdict
from roboprobe.runner.confirmations import CONFIRM_PHASE, ConfirmationService
from roboprobe.runner.replay import ReplayRequest, enqueue_replays
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.store.ids import new_uuid
from roboprobe.store.orm import FailureModeMemberRow
from roboprobe.store.records import (
    CampaignRecord,
    FailureModeMemberRecord,
    FailureModeRecord,
    NewRun,
    RunRecord,
    SpaceRecord,
    SutProfileRecord,
)

REPO = Path(__file__).resolve().parents[4]
WAREHOUSE = REPO / "configs" / "scenario_spaces" / "warehouse_v1.yaml"


def _seed_confirmation(uow_factory, space: ScenarioSpace):
    with uow_factory() as uow:
        sut_id = f"p-{new_uuid()}"
        uow.sut_profiles.add(
            SutProfileRecord(id=sut_id, backend="kinematic2d", config={}, config_hash="h")
        )
        uow.spaces.add(
            SpaceRecord(
                id=space.id,
                version=space.version,
                name=space.name,
                definition=yaml.safe_load(WAREHOUSE.read_text(encoding="utf-8")),
            )
        )
        cid = new_uuid()
        uow.campaigns.add(
            CampaignRecord(
                id=cid,
                name="c",
                space_id=space.id,
                space_version=space.version,
                sut_profile_id=sut_id,
                backend="kinematic2d",
                strategy_id="S-RANDOM",
                seed=3,
                budget=50,
                oracle_config={},
                status=CampaignStatus.COMPLETED,
            )
        )
        values = dict(space.nominal_values())
        values["robot.max_speed"] = 0.4
        values["env.illuminance"] = 15.0
        unit = space.to_unit(values)
        rid = new_uuid()
        uow.runs.import_many(
            [
                RunRecord(
                    id=rid,
                    campaign_id=cid,
                    ordinal=0,
                    repeat_index=0,
                    backend="kinematic2d",
                    scenario_hash="h0",
                    scenario_values={str(k): v for k, v in values.items()},  # type: ignore[misc]
                    x_unit=tuple(float(x) for x in unit),
                    seed=0,
                    phase="explore",
                    proposal={},
                    tags=(),
                    replay_of=None,
                    status=RunStatus.DONE,
                    priority=100,
                    attempt=1,
                    worker_id=None,
                    verdict=Verdict.FAIL,
                    robustness=-0.3,
                    primary_failure=FailureClass.COL.value,
                    warnings=(),
                    metrics={},
                    infra_error=None,
                    manifest=None,
                )
            ]
        )
        mid = new_uuid()
        uow.modes.upsert_modes(
            cid,
            [
                FailureModeRecord(
                    id=mid,
                    campaign_id=cid,
                    code="FM-A",
                    label="GT-A",
                    primary_class=FailureClass.COL.value,
                    class_mix={FailureClass.COL.value: 1.0},
                    size=3,
                    param_ranges={
                        "robot.max_speed": {
                            "unit": "m/s",
                            "q05": 0.3,
                            "q95": 0.5,
                            "space_coverage": 0.1,
                        },
                        "env.illuminance": {
                            "unit": "lx",
                            "q05": 10.0,
                            "q95": 20.0,
                            "space_coverage": 0.1,
                        },
                        "sensor.lidar_noise_std": {
                            "unit": "-",
                            "q05": 0.05,
                            "q95": 0.1,
                            "space_coverage": 0.1,
                        },
                    },
                    characteristic=(
                        "robot.max_speed",
                        "env.illuminance",
                        "sensor.lidar_noise_std",
                    ),
                    medoid_run_id=rid,
                    minimal_run_id=rid,
                )
            ],
            [FailureModeMemberRecord(mode_id=mid, run_id=rid, membership=1.0)],
        )
        (normal_run,) = uow.runs.insert_batch(
            [
                NewRun(
                    campaign_id=cid,
                    ordinal=1,
                    repeat_index=0,
                    backend="kinematic2d",
                    scenario_hash="h1",
                    scenario_values=values,
                    x_unit=tuple(float(x) for x in unit),
                    seed=1,
                    phase="explore",
                )
            ]
        )
        uow.commit()

    return cid, rid, mid, normal_run


def _queue_manual_probe(settings: RoboProbeSettings, cid: UUID, space: ScenarioSpace) -> UUID:
    app = create_app(settings)
    app.state.event_hub_autostart = False
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/campaigns/{cid}/runs",
            json={"values": space.nominal_values(), "repeats": 1, "tags": ["probe"]},
        )
    assert response.status_code == HTTPStatus.CREATED, response.text
    return UUID(response.json()["run_ids"][0])


@pytest.mark.integration
def test_confirmations_postgres_roundtrip(
    uow_factory, pg_engine, postgres_url: str, tmp_path: Path
) -> None:
    space = ScenarioSpace.from_yaml(WAREHOUSE, base_dir=REPO)
    cid, rid, mid, normal_run = _seed_confirmation(uow_factory, space)

    def load_space(_sid: str, _ver: str) -> ScenarioSpace:
        return space

    interaction = InteractionSettings(repeats=1, success_ratio=0.67)
    svc = ConfirmationService(
        uow_factory,
        interaction=interaction,
        confirm_priority=10,
        load_space=load_space,
    )
    first = svc.request(cid, mid)
    assert len(first) == 3 + 3 + 1  # singles + pairs + full
    assert svc.request(cid, mid) == first
    replays = enqueue_replays(uow_factory, ReplayRequest(rid))
    with uow_factory() as uow:
        hist = uow.runs.history(cid)
        assert all(obs.run_id not in set(first) for obs in hist)
        confirms = [r for r in uow.runs.list_for_campaign(cid).items if r.phase == CONFIRM_PHASE]
        assert len(confirms) == len(first)
        uow.modes.patch(mid, label="User label", status="accepted")

    settings = load_settings(
        {
            "database.url": postgres_url,
            "storage.workdir_root": str(tmp_path / "work"),
            "storage.artifact_root": str(tmp_path / "artefacts"),
            "worker.backend": "kinematic2d",
            "analysis.interaction.repeats": interaction.repeats,
            "analysis.interaction.success_ratio": interaction.success_ratio,
            "observability.metrics_enabled": False,
        }
    )
    expected = set(first) | set(replays) | {_queue_manual_probe(settings, cid, space)}
    finished = set()
    infra = build_infrastructure(settings)
    try:
        worker = build_worker(settings, task=space.task, infra=infra)
        assert infra.queue.depth("kinematic2d") == len(expected)
        for _ in expected:
            claimed = worker.claim()
            assert claimed is not None
            worker.execute(claimed)
            finished.add(claimed.run_id)
            with uow_factory() as uow:
                mode = uow.modes.get(mid)
                assert mode is not None
                assert (mode.interaction is not None) == (set(first) <= finished)
        assert worker.claim() is None
    finally:
        infra.close()
    assert finished == expected
    assert svc.request(cid, mid) == first
    with uow_factory() as uow:
        mode = uow.modes.get(mid)
        assert mode is not None and mode.interaction is not None
        assert mode.label == "User label" and mode.status == "accepted"
        assert mode.etag_version == 3
        assert uow.runs.get(normal_run).status is RunStatus.PENDING
        assert uow.campaigns.get(cid).status is CampaignStatus.COMPLETED
        assert all(uow.runs.get(run_id).status is RunStatus.DONE for run_id in finished)
        updates = uow.events.since(0, campaign_id=cid)
        assert sum(ev.payload.get("reason") == "interaction_confirmed" for ev in updates) == 1
    with pg_engine.connect() as connection:
        members = connection.scalars(
            select(FailureModeMemberRow.run_id).where(FailureModeMemberRow.mode_id == mid)
        )
        assert list(members) == [rid]
