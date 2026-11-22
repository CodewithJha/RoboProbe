"""Analysis/experiment/worker repository tests (T-011b)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256

import pytest
from tests.integration.store._seed import seed_campaign, seed_worker

from roboprobe.store.ids import new_uuid
from roboprobe.store.records import (
    AnalysisRecord,
    ExperimentRecord,
    FailureModeMemberRecord,
    FailureModeRecord,
    RiskMapRecord,
    WorkerRecord,
)
from roboprobe.store.uow import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.integration


def test_modes_preserve_user_labels(uow_factory: Callable[[], SqlAlchemyUnitOfWork]) -> None:
    with uow_factory() as uow:
        cid, ids = seed_campaign(uow, n_runs=1)
        mid = new_uuid()
        uow.modes.upsert_modes(
            cid,
            [
                FailureModeRecord(
                    id=mid,
                    campaign_id=cid,
                    code="FM-01",
                    label="auto",
                    label_is_user=True,
                    primary_class="F-COL",
                    class_mix={},
                    size=1,
                    param_ranges={},
                    characteristic=(),
                )
            ],
            [FailureModeMemberRecord(mode_id=mid, run_id=ids[0], membership=0.9)],
        )
        uow.modes.upsert_modes(
            cid,
            [
                FailureModeRecord(
                    id=new_uuid(),
                    campaign_id=cid,
                    code="FM-01",
                    label="cluster-new",
                    label_is_user=False,
                    primary_class="F-NEAR",
                    class_mix={},
                    size=2,
                    param_ranges={},
                    characteristic=("tight",),
                )
            ],
            [],
        )
        modes = uow.modes.list_for_campaign(cid)
        assert len(modes) == 1
        assert modes[0].label == "auto"
        assert modes[0].primary_class == "F-NEAR"


def test_worker_heartbeat_and_experiment(uow_factory: Callable[[], SqlAlchemyUnitOfWork]) -> None:
    with uow_factory() as uow:
        cid, _ = seed_campaign(uow, n_runs=0)
        seed_worker(uow)
        at = datetime.now(UTC)
        uow.workers.heartbeat("host:1:0", at=at)
        got = uow.workers.get("host:1:0")
        assert got is not None
        assert got.last_heartbeat is not None
        uow.experiments.add(
            ExperimentRecord(id=new_uuid(), name="e", design={"n": 1}, status="CREATED")
        )
        aid = new_uuid()
        uow.analyses.add(
            AnalysisRecord(
                id=aid,
                campaign_id=cid,
                kind="final",
                status="DONE",
                n_runs=0,
            )
        )
        uow.risk_maps.add(
            RiskMapRecord(
                id=new_uuid(),
                campaign_id=cid,
                n_obs=0,
                thresholds={},
                volumes={},
                robustness_score=0.5,
            )
        )
        assert uow.risk_maps.latest(cid) is not None
        assert uow.workers.online("kinematic2d")


def test_worker_cursor_hides_raw_identifier_and_keeps_its_position(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    raw_ids = ["office-a.private:101:0", "office-b.private:101:0"]
    with uow_factory() as uow:
        for raw_id in raw_ids:
            uow.workers.register(
                WorkerRecord(
                    id=raw_id,
                    backend="kinematic2d",
                    status="IDLE",
                    capabilities={},
                    version="1",
                )
            )
        first = uow.workers.list(limit=1)
        assert first.next_cursor == sha256(first.items[0].id.encode("utf-8")).hexdigest()
        second = uow.workers.list(limit=1, cursor=first.next_cursor)
        assert second.next_cursor is None
        assert sorted([first.items[0].id, second.items[0].id]) == raw_ids
