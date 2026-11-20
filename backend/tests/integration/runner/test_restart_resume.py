"""Orchestrator restart resumes strategy checkpoints (T-041b)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from tests.fakes.store import InMemoryUnitOfWork
from tests.unit.selection.conftest import load_space

from roboprobe.core.clock import FakeClock
from roboprobe.core.settings.runner import RunnerSettings
from roboprobe.core.settings.selection import SelectionDefaults
from roboprobe.core.types import CampaignStatus
from roboprobe.runner.checkpoint import CheckpointStore
from roboprobe.runner.loop import CampaignLoop
from roboprobe.runner.scheduler import Scheduler
from roboprobe.selection.base import StrategyContext
from roboprobe.selection.baselines.sobol import SobolStrategy
from roboprobe.store.ids import new_uuid
from roboprobe.store.records import CampaignRecord, SpaceRecord, SutProfileRecord, WorkerRecord

pytestmark = pytest.mark.integration


def test_restart_resume_matches_uninterrupted() -> None:
    space, _ = load_space(dim=3, budget=64, seed=9)
    settings = RunnerSettings(inflight_factor=1.0, max_batch_size=32)

    def make_uow_campaign(seed: int = 9):
        uow = InMemoryUnitOfWork()
        cid = new_uuid()
        with uow:
            uow.sut_profiles.add(
                SutProfileRecord(id="sut", backend="kinematic2d", config={}, config_hash="c" * 16)
            )
            uow.spaces.add(SpaceRecord(id="s", version="v", name="n", definition={}))
            uow.campaigns.add(
                CampaignRecord(
                    id=cid,
                    name="c",
                    space_id="s",
                    space_version="v",
                    sut_profile_id="sut",
                    backend="kinematic2d",
                    strategy_id="S-SOBOL",
                    seed=seed,
                    budget=64,
                    batch_size=4,
                    oracle_config={},
                    status=CampaignStatus.RUNNING,
                )
            )
            for i in range(4):
                uow.workers.register(
                    WorkerRecord(
                        id=f"w:{i}:0",
                        backend="kinematic2d",
                        status="IDLE",
                        capabilities={},
                        version="0.0.1",
                    )
                )
            uow.commit()
        return uow, cid

    # Uninterrupted: two ticks
    uow_a, cid_a = make_uow_campaign()
    ctx_a = StrategyContext(space=space, budget=64, seed=9, batch_size=4, params={})
    loop_a = CampaignLoop(
        cid_a,
        uow_factory=lambda: uow_a,
        settings=settings,
        selection=SelectionDefaults(),
        space=space,
        strategy=SobolStrategy(ctx_a),
        scheduler=Scheduler(settings),
        clock=FakeClock(start=datetime(2020, 1, 1, tzinfo=UTC)),
    )
    loop_a.step()
    # Mark first batch done so free slots open for tick 2.
    with uow_a:
        for run in uow_a.runs.list_for_campaign(cid_a).items:
            uow_a.runs._db.runs[run.id] = run.model_copy(
                update={
                    "status": __import__(
                        "roboprobe.core.types", fromlist=["RunStatus"]
                    ).RunStatus.DONE,
                    "verdict": __import__(
                        "roboprobe.core.types", fromlist=["Verdict"]
                    ).Verdict.PASS,
                    "robustness": 0.5,
                }
            )
        uow_a.commit()
    loop_a.step()
    with uow_a:
        uninterrupted = [r.scenario_hash for r in uow_a.runs.list_for_campaign(cid_a).items]

    # Interrupted: tick 1, checkpoint, restore, tick 2
    uow_b, cid_b = make_uow_campaign()
    ctx_b = StrategyContext(space=space, budget=64, seed=9, batch_size=4, params={})
    strat_b = SobolStrategy(ctx_b)
    checkpoints = CheckpointStore(lambda: uow_b)
    loop_b = CampaignLoop(
        cid_b,
        uow_factory=lambda: uow_b,
        settings=settings,
        selection=SelectionDefaults(),
        space=space,
        strategy=strat_b,
        scheduler=Scheduler(settings),
        clock=FakeClock(start=datetime(2020, 1, 1, tzinfo=UTC)),
    )
    loop_b.step()
    checkpoints.save(cid_b, strat_b, n_obs=0)
    # "Restart"
    ctx_c = StrategyContext(space=space, budget=64, seed=9, batch_size=4, params={})
    strat_c = SobolStrategy(ctx_c)
    assert checkpoints.restore(cid_b, strat_c)
    with uow_b:
        for run in uow_b.runs.list_for_campaign(cid_b).items:
            uow_b.runs._db.runs[run.id] = run.model_copy(
                update={
                    "status": __import__(
                        "roboprobe.core.types", fromlist=["RunStatus"]
                    ).RunStatus.DONE,
                    "verdict": __import__(
                        "roboprobe.core.types", fromlist=["Verdict"]
                    ).Verdict.PASS,
                    "robustness": 0.5,
                }
            )
        uow_b.commit()
    loop_c = CampaignLoop(
        cid_b,
        uow_factory=lambda: uow_b,
        settings=settings,
        selection=SelectionDefaults(),
        space=space,
        strategy=strat_c,
        scheduler=Scheduler(settings),
        clock=FakeClock(start=datetime(2020, 1, 1, tzinfo=UTC)),
    )
    loop_c.step()
    with uow_b:
        resumed = [r.scenario_hash for r in uow_b.runs.list_for_campaign(cid_b).items]
    assert resumed == uninterrupted
