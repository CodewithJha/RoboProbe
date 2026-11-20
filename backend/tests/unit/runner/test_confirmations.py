"""Unit tests for ConfirmationService (T-074b)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from tests.fakes.store import InMemoryUnitOfWork

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


@pytest.fixture
def space() -> ScenarioSpace:
    return ScenarioSpace.from_yaml(WAREHOUSE, base_dir=REPO)


def _seed_mode(uow: InMemoryUnitOfWork, space: ScenarioSpace) -> tuple[UUID, UUID]:
    sut_id = f"p-{new_uuid()}"
    uow.sut_profiles.add(
        SutProfileRecord(id=sut_id, backend="kinematic2d", config={}, config_hash="h")
    )
    uow.spaces.add(
        SpaceRecord(
            id=space.id,
            version=space.version,
            name=space.name,
            definition={},
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
            seed=7,
            budget=100,
            oracle_config={},
            status=CampaignStatus.RUNNING,
        )
    )
    values = dict(space.nominal_values())
    values["robot.max_speed"] = 0.45
    values["env.illuminance"] = 12.0
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
                robustness=-0.2,
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
                code="FM-01",
                label="pair",
                primary_class=FailureClass.COL.value,
                class_mix={FailureClass.COL.value: 1.0},
                size=1,
                param_ranges={
                    "robot.max_speed": {
                        "unit": "m/s",
                        "q05": 0.4,
                        "q95": 0.5,
                        "space_coverage": 0.1,
                    },
                    "env.illuminance": {
                        "unit": "lx",
                        "q05": 10.0,
                        "q95": 20.0,
                        "space_coverage": 0.1,
                    },
                },
                characteristic=("robot.max_speed", "env.illuminance"),
                medoid_run_id=rid,
                minimal_run_id=rid,
            )
        ],
        [],
    )
    return cid, mid


def test_request_idempotent_and_excludes_from_history(space: ScenarioSpace) -> None:
    shared = InMemoryUnitOfWork()

    def factory() -> InMemoryUnitOfWork:
        return shared

    with shared as uow:
        cid, mid = _seed_mode(uow, space)
        uow.commit()

    svc = ConfirmationService(
        factory,
        interaction=InteractionSettings(repeats=2, success_ratio=0.67),
        confirm_priority=10,
        load_space=lambda _i, _v: space,
    )
    first = svc.request(cid, mid)
    second = svc.request(cid, mid)
    assert first == second
    assert len(first) > 0

    with shared as uow:
        page = uow.runs.list_for_campaign(cid)
        confirms = [r for r in page.items if r.phase == CONFIRM_PHASE]
        assert len(confirms) == len(first)
        assert all(r.priority == 10 for r in confirms)
        # Finish confirms as FAIL so they would appear in history if not excluded.
        for run in confirms:
            uow.runs._db.runs[run.id] = run.model_copy(
                update={"status": RunStatus.DONE, "verdict": Verdict.FAIL, "robustness": -0.1}
            )
        hist = uow.runs.history(cid)
        assert all(obs.run_id not in set(first) for obs in hist)
        hist_all = uow.runs.history(cid, exclude_phases=frozenset())
        assert {obs.run_id for obs in hist_all} >= set(first)


def test_on_run_finished_persists_interaction(space: ScenarioSpace) -> None:
    shared = InMemoryUnitOfWork()

    def factory() -> InMemoryUnitOfWork:
        return shared

    with shared as uow:
        cid, mid = _seed_mode(uow, space)
        uow.commit()

    svc = ConfirmationService(
        factory,
        interaction=InteractionSettings(repeats=1, success_ratio=0.67),
        confirm_priority=10,
        load_space=lambda _i, _v: space,
    )
    ids = svc.request(cid, mid)
    with shared as uow:
        for run_id in ids:
            run = uow.runs.get(run_id)
            assert run is not None
            uow.runs._db.runs[run_id] = run.model_copy(
                update={
                    "status": RunStatus.DONE,
                    "verdict": Verdict.FAIL,
                    "robustness": -0.2,
                    "primary_failure": FailureClass.COL.value,
                }
            )
        last = uow.runs.get(ids[-1])
        assert last is not None
        uow.commit()

    svc.on_run_finished(last)
    with shared as uow:
        mode = uow.modes.get(mid)
        assert mode is not None
        assert mode.interaction is not None
        assert mode.interaction["status"] in {"CONFIRMED", "NOT_INTERACTION", "INCONCLUSIVE"}
        topics = [e.topic for e in uow.events.since(0)]
        assert "mode.discovered" in topics
        assert "campaign.updated" in topics
