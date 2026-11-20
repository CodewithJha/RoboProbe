"""Campaign lifecycle transition table and CampaignService (T-041c)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from tests.fakes.store import InMemoryUnitOfWork

from roboprobe.core.errors import ConflictError, ErrorCode, NotFoundError
from roboprobe.core.types import CampaignStatus, RunStatus
from roboprobe.runner.lifecycle import (
    ALLOWED,
    IDEMPOTENT,
    CampaignCommand,
    CampaignService,
    transition,
)
from roboprobe.store.records import CampaignRecord, NewRun, SpaceRecord, SutProfileRecord

pytestmark = pytest.mark.unit


def _seed_campaign(
    uow: InMemoryUnitOfWork, *, status: CampaignStatus = CampaignStatus.CREATED
) -> object:
    sut_id = f"sut-{uuid4()}"
    space_id = f"space-{uuid4()}"
    with uow:
        uow.sut_profiles.add(
            SutProfileRecord(id=sut_id, backend="kinematic2d", config={}, config_hash="h" * 16)
        )
        uow.spaces.add(SpaceRecord(id=space_id, version="v1", name="n", definition={}))
        cid = uuid4()
        uow.campaigns.add(
            CampaignRecord(
                id=cid,
                name="c",
                space_id=space_id,
                space_version="v1",
                sut_profile_id=sut_id,
                backend="kinematic2d",
                strategy_id="S-RANDOM",
                seed=1,
                budget=10,
                oracle_config={},
                status=status,
            )
        )
        uow.commit()
    return cid


@pytest.mark.parametrize(
    ("current", "command", "expected"),
    [(cur, cmd, nxt) for (cur, cmd), nxt in ALLOWED.items()],
)
def test_allowed_transitions(
    current: CampaignStatus, command: CampaignCommand, expected: CampaignStatus
) -> None:
    assert transition(current, command) is expected


@pytest.mark.parametrize(
    ("current", "command", "expected"),
    [(cur, cmd, nxt) for (cur, cmd), nxt in IDEMPOTENT.items()],
)
def test_idempotent_transitions(
    current: CampaignStatus, command: CampaignCommand, expected: CampaignStatus
) -> None:
    assert transition(current, command) is expected


@pytest.mark.parametrize(
    ("current", "command"),
    [
        (CampaignStatus.COMPLETED, CampaignCommand.PAUSE),
        (CampaignStatus.FAILED, CampaignCommand.START),
        (CampaignStatus.CANCELLED, CampaignCommand.RESUME),
        (CampaignStatus.CREATED, CampaignCommand.PAUSE),
        (CampaignStatus.CREATED, CampaignCommand.RESUME),
        (CampaignStatus.ANALYZING, CampaignCommand.PAUSE),
        (CampaignStatus.RUNNING, CampaignCommand.COMPLETE),
        (CampaignStatus.PAUSED, CampaignCommand.FAIL),
    ],
)
def test_forbidden_transitions_raise(current: CampaignStatus, command: CampaignCommand) -> None:
    with pytest.raises(ConflictError) as info:
        transition(current, command)
    assert info.value.code is ErrorCode.CAMPAIGN_INVALID_TRANSITION


def test_service_start_pause_resume_cancel() -> None:
    uow = InMemoryUnitOfWork()
    cid = _seed_campaign(uow)
    svc = CampaignService(lambda: uow)

    assert svc.start(cid) is CampaignStatus.RUNNING
    assert svc.pause(cid) is CampaignStatus.PAUSED
    assert svc.pause(cid) is CampaignStatus.PAUSED  # idempotent
    assert svc.resume(cid) is CampaignStatus.RUNNING
    assert svc.cancel(cid) is CampaignStatus.CANCELLED

    with uow:
        camp = uow.campaigns.get(cid)
        assert camp is not None
        assert camp.status is CampaignStatus.CANCELLED
        topics = [e.topic for e in uow.events.since(0)]
        assert "campaign.updated" in topics


def test_cancel_marks_pending_runs() -> None:
    uow = InMemoryUnitOfWork()
    cid = _seed_campaign(uow, status=CampaignStatus.RUNNING)
    with uow:
        uow.runs.insert_batch(
            [
                NewRun(
                    campaign_id=cid,
                    ordinal=0,
                    backend="kinematic2d",
                    scenario_hash="a" * 16,
                    scenario_values={},
                    x_unit=(0.1,),
                    seed=1,
                    phase="baseline",
                ),
                NewRun(
                    campaign_id=cid,
                    ordinal=1,
                    backend="kinematic2d",
                    scenario_hash="b" * 16,
                    scenario_values={},
                    x_unit=(0.2,),
                    seed=2,
                    phase="baseline",
                ),
            ]
        )
        uow.commit()

    svc = CampaignService(lambda: uow)
    assert svc.cancel(cid) is CampaignStatus.CANCELLED
    with uow:
        page = uow.runs.list_for_campaign(cid)
        assert all(r.status is RunStatus.CANCELLED for r in page.items)


def test_mark_analyzing_complete_fail() -> None:
    uow = InMemoryUnitOfWork()
    cid = _seed_campaign(uow, status=CampaignStatus.RUNNING)
    svc = CampaignService(lambda: uow)
    assert svc.mark_analyzing(cid, reason="budget") is CampaignStatus.ANALYZING
    assert svc.complete(cid) is CampaignStatus.COMPLETED
    assert svc.mark_analyzing(cid) is CampaignStatus.ANALYZING  # re-analyze
    assert svc.fail(cid, reason="boom") is CampaignStatus.FAILED


def test_missing_campaign() -> None:
    uow = InMemoryUnitOfWork()
    svc = CampaignService(lambda: uow)
    with pytest.raises(NotFoundError):
        svc.start(uuid4())
