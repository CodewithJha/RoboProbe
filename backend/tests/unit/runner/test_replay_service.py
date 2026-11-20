"""Unit tests for replay enqueue + agreement (runner/replay.py)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from tests.fakes.store import InMemoryUnitOfWork

from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.core.types import CampaignStatus, RunStatus, Verdict
from roboprobe.runner.replay import ReplayRequest, enqueue_replays, summarise_agreement
from roboprobe.store.records import (
    CampaignRecord,
    NewRun,
    SpaceRecord,
    SutProfileRecord,
)

pytestmark = pytest.mark.unit


def _campaign_with_done_run(
    uow: InMemoryUnitOfWork,
    *,
    fresh_seed: int = 99,
) -> tuple[object, object]:
    cid = uuid4()
    with uow:
        uow.spaces.add(SpaceRecord(id="s", version="v", name="n", definition={}))
        uow.sut_profiles.add(
            SutProfileRecord(id="sut", backend="kinematic2d", config={}, config_hash="c" * 16)
        )
        uow.campaigns.add(
            CampaignRecord(
                id=cid,
                name="c",
                space_id="s",
                space_version="v",
                sut_profile_id="sut",
                backend="kinematic2d",
                strategy_id="S-RANDOM",
                seed=1,
                budget=5,
                oracle_config={},
                status=CampaignStatus.RUNNING,
            )
        )
        (rid,) = uow.runs.insert_batch(
            [
                NewRun(
                    campaign_id=cid,
                    ordinal=0,
                    backend="kinematic2d",
                    scenario_hash="a" * 16,
                    scenario_values={"robot.max_speed": 0.3},
                    x_unit=(0.1, 0.2),
                    seed=fresh_seed,
                    phase="baseline",
                )
            ]
        )
        src = uow.runs.get(rid)
        assert src is not None
        uow.runs._db.runs[rid] = src.model_copy(
            update={
                "status": RunStatus.DONE,
                "verdict": Verdict.PASS,
                "robustness": 0.8,
                "primary_failure": None,
            }
        )
        uow.commit()
    return cid, rid


def test_enqueue_replays_copies_scenario() -> None:
    uow = InMemoryUnitOfWork()
    _, source_id = _campaign_with_done_run(uow)
    factory = lambda: uow  # noqa: E731
    ids = enqueue_replays(factory, ReplayRequest(run_id=source_id, repeats=2, fresh_seeds=False))
    assert len(ids) == 2
    with uow:
        for rid in ids:
            row = uow.runs.get(rid)
            assert row is not None
            assert row.replay_of == source_id
            assert row.phase == "replay"
            assert row.status is RunStatus.PENDING


def test_enqueue_replays_fresh_seeds() -> None:
    uow = InMemoryUnitOfWork()
    _, source_id = _campaign_with_done_run(uow, fresh_seed=42)
    factory = lambda: uow  # noqa: E731
    (replay_id,) = enqueue_replays(
        factory, ReplayRequest(run_id=source_id, repeats=1, fresh_seeds=True)
    )
    with uow:
        src = uow.runs.get(source_id)
        rep = uow.runs.get(replay_id)
        assert src is not None and rep is not None
        assert rep.seed != src.seed


def test_enqueue_replays_rejects_non_done() -> None:
    uow = InMemoryUnitOfWork()
    cid = uuid4()
    with uow:
        uow.spaces.add(SpaceRecord(id="s", version="v", name="n", definition={}))
        uow.sut_profiles.add(
            SutProfileRecord(id="sut", backend="fake", config={}, config_hash="d" * 16)
        )
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
                budget=1,
                oracle_config={},
                status=CampaignStatus.RUNNING,
            )
        )
        (rid,) = uow.runs.insert_batch(
            [
                NewRun(
                    campaign_id=cid,
                    ordinal=0,
                    backend="fake",
                    scenario_hash="e" * 16,
                    scenario_values={},
                    x_unit=(0.0,),
                    seed=1,
                    phase="baseline",
                )
            ]
        )
        uow.commit()
    with pytest.raises(ValidationError, match="DONE"):
        enqueue_replays(lambda: uow, ReplayRequest(run_id=rid))


def test_enqueue_replays_missing_run() -> None:
    uow = InMemoryUnitOfWork()
    with pytest.raises(NotFoundError):
        enqueue_replays(lambda: uow, ReplayRequest(run_id=uuid4()))


def test_summarise_agreement_counts() -> None:
    uow = InMemoryUnitOfWork()
    _, source_id = _campaign_with_done_run(uow)
    factory = lambda: uow  # noqa: E731
    ids = enqueue_replays(factory, ReplayRequest(run_id=source_id, repeats=2))
    with uow:
        for rid in ids:
            row = uow.runs.get(rid)
            assert row is not None
            uow.runs._db.runs[rid] = row.model_copy(
                update={"status": RunStatus.DONE, "verdict": Verdict.PASS}
            )
        uow.commit()
    summary = summarise_agreement(factory, source_id, ids)
    assert summary.agreements == 2
    assert summary.disagreements == 0
    assert summary.all_agree
    assert summary.trace_matches is None


def test_summarise_agreement_trace_hashes() -> None:
    uow = InMemoryUnitOfWork()
    _, source_id = _campaign_with_done_run(uow)
    factory = lambda: uow  # noqa: E731
    (replay_id,) = enqueue_replays(factory, ReplayRequest(run_id=source_id, repeats=1))
    hashes = {source_id: "aaa", replay_id: "aaa"}
    summary = summarise_agreement(factory, source_id, (replay_id,), trace_hashes=hashes)
    assert summary.trace_matches == 1