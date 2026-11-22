"""CampaignLoop.step enqueue behaviour (T-041a)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import numpy as np
import numpy.typing as npt
import pytest
from tests.fakes.store import InMemoryUnitOfWork
from tests.unit.selection.conftest import load_space

from roboprobe.core.clock import FakeClock
from roboprobe.core.settings.runner import RunnerSettings
from roboprobe.core.settings.selection import SelectionDefaults
from roboprobe.core.types import CampaignStatus, Observation, Proposal
from roboprobe.runner.loop import CampaignLoop
from roboprobe.runner.scheduler import Scheduler
from roboprobe.selection.base import StrategyContext
from roboprobe.selection.baselines.random import RandomStrategy
from roboprobe.store.records import (
    CampaignRecord,
    SpaceRecord,
    SutProfileRecord,
    WorkerRecord,
)

pytestmark = pytest.mark.unit


def _campaign(  # noqa: PLR0913
    uow: InMemoryUnitOfWork,
    *,
    seed: int,
    budget: int = 20,
    batch_size: int = 4,
    repeats: int = 1,
    workers: int = 2,
) -> object:
    cid = uuid4()
    with uow:
        uow.sut_profiles.add(
            SutProfileRecord(id="sut", backend="kinematic2d", config={}, config_hash="c" * 16)
        )
        uow.spaces.add(SpaceRecord(id="warehouse_v1", version="v", name="n", definition={}))
        uow.campaigns.add(
            CampaignRecord(
                id=cid,
                name="c",
                space_id="warehouse_v1",
                space_version="v",
                sut_profile_id="sut",
                backend="kinematic2d",
                strategy_id="S-RANDOM",
                seed=seed,
                budget=budget,
                batch_size=batch_size,
                repeats=repeats,
                oracle_config={},
                status=CampaignStatus.RUNNING,
            )
        )
        for i in range(workers):
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
    return cid


def _loop(
    uow: InMemoryUnitOfWork, cid: object, *, seed: int, settings: RunnerSettings | None = None
) -> CampaignLoop:
    space, _ = load_space(dim=3, budget=64, seed=seed)
    ctx = StrategyContext(space=space, budget=64, seed=seed, batch_size=4, params={})
    settings = settings or RunnerSettings(inflight_factor=1.0, max_batch_size=32)
    return CampaignLoop(
        cid,  # type: ignore[arg-type]
        uow_factory=lambda: uow,
        settings=settings,
        selection=SelectionDefaults(propose_timeout_s=5.0),
        space=space,
        strategy=RandomStrategy(ctx),
        scheduler=Scheduler(settings),
        clock=FakeClock(start=datetime(2020, 1, 1, tzinfo=UTC)),
    )


def test_enqueues_for_worker_budget() -> None:
    uow = InMemoryUnitOfWork()
    cid = _campaign(uow, seed=1, budget=10, batch_size=4, workers=2)
    loop = _loop(uow, cid, seed=1, settings=RunnerSettings(inflight_factor=1.0, max_batch_size=32))
    n = loop.step()
    # target = ceil(min(4,2)*1.0) = 2
    assert n == 2
    with uow:
        page = uow.runs.list_for_campaign(cid)  # type: ignore[arg-type]
        assert len(page.items) == 2


def test_enqueued_proposal_keeps_predictions(monkeypatch: pytest.MonkeyPatch) -> None:
    uow = InMemoryUnitOfWork()
    cid = _campaign(uow, seed=3, workers=2)
    propose = RandomStrategy.propose

    def with_prediction(
        self: RandomStrategy,
        history: Sequence[Observation],
        pending: Sequence[npt.NDArray[np.floating[Any]]],
        q: int,
    ) -> list[Proposal]:
        first, second = propose(self, history, pending, q)
        return [first.model_copy(update={"predicted_mean": -0.3, "predicted_std": 0.0}), second]

    monkeypatch.setattr(RandomStrategy, "propose", with_prediction)

    assert _loop(uow, cid, seed=3).step() == 2
    with uow:
        first, second = uow.runs.list_for_campaign(cid).items  # type: ignore[arg-type]
    assert first.proposal["predicted_mean"] == -0.3
    assert first.proposal["predicted_std"] == 0.0
    assert "predicted_mean" not in second.proposal
    assert "predicted_std" not in second.proposal


def test_identical_seeds_identical_sequences() -> None:
    settings = RunnerSettings(inflight_factor=1.0, max_batch_size=32)
    uow_a, uow_b = InMemoryUnitOfWork(), InMemoryUnitOfWork()
    cid_a = _campaign(uow_a, seed=42, workers=4, batch_size=4)
    cid_b = _campaign(uow_b, seed=42, workers=4, batch_size=4)
    _loop(uow_a, cid_a, seed=42, settings=settings).step()
    _loop(uow_b, cid_b, seed=42, settings=settings).step()
    with uow_a, uow_b:
        a = [r.scenario_hash for r in uow_a.runs.list_for_campaign(cid_a).items]  # type: ignore[arg-type]
        b = [r.scenario_hash for r in uow_b.runs.list_for_campaign(cid_b).items]  # type: ignore[arg-type]
        assert a == b
        assert [r.seed for r in uow_a.runs.list_for_campaign(cid_a).items] == [  # type: ignore[arg-type]
            r.seed
            for r in uow_b.runs.list_for_campaign(cid_b).items  # type: ignore[arg-type]
        ]


def test_repeated_tick_after_crash_is_idempotent() -> None:
    uow = InMemoryUnitOfWork()
    cid = _campaign(uow, seed=7, workers=2, batch_size=4)
    settings = RunnerSettings(inflight_factor=1.0, max_batch_size=32)
    loop = _loop(uow, cid, seed=7, settings=settings)
    assert loop.step() == 2
    # Simulate crash + retry: inflight already at target → nothing new.
    assert loop.step() == 0
    with uow:
        assert len(uow.runs.list_for_campaign(cid).items) == 2  # type: ignore[arg-type]
