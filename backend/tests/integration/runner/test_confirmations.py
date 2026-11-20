"""Integration: confirmation enqueue + history exclusion (T-074b).

Full k2d GT-A confirmation needs a worker; this test covers the Postgres
path for request idempotency and history exclusion when Testcontainers is available.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from roboprobe.core.settings.analysis import InteractionSettings
from roboprobe.core.types import CampaignStatus, FailureClass, RunStatus, Verdict
from roboprobe.runner.confirmations import CONFIRM_PHASE, ConfirmationService
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.store.ids import new_uuid
from roboprobe.store.records import (
    CampaignRecord,
    FailureModeRecord,
    RunRecord,
    SpaceRecord,
    SutProfileRecord,
)

REPO = Path(__file__).resolve().parents[4]
WAREHOUSE = REPO / "configs" / "scenario_spaces" / "warehouse_v1.yaml"


@pytest.mark.integration
def test_confirmations_postgres_roundtrip(uow_factory) -> None:
    space = ScenarioSpace.from_yaml(WAREHOUSE, base_dir=REPO)

    def load_space(_sid: str, _ver: str) -> ScenarioSpace:
        return space

    with uow_factory() as uow:
        sut_id = f"p-{new_uuid()}"
        uow.sut_profiles.add(
            SutProfileRecord(id=sut_id, backend="kinematic2d", config={}, config_hash="h")
        )
        uow.spaces.add(
            SpaceRecord(id=space.id, version=space.version, name=space.name, definition={})
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
                status=CampaignStatus.RUNNING,
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
            [],
        )
        uow.commit()

    svc = ConfirmationService(
        uow_factory,
        interaction=InteractionSettings(repeats=3, success_ratio=0.67),
        confirm_priority=10,
        load_space=load_space,
    )
    first = svc.request(cid, mid)
    assert len(first) == 3 * (3 + 3 + 1)  # singles + pairs + full, each x3
    assert svc.request(cid, mid) == first
    with uow_factory() as uow:
        hist = uow.runs.history(cid)
        assert all(obs.run_id not in set(first) for obs in hist)
        confirms = [r for r in uow.runs.list_for_campaign(cid).items if r.phase == CONFIRM_PHASE]
        assert len(confirms) == len(first)
