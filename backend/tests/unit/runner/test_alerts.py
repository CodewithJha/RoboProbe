"""Alert evaluator (T-042b)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from tests.fakes.store import InMemoryUnitOfWork

from roboprobe.core.settings.runner import RunnerSettings
from roboprobe.core.settings.storage import StorageSettings
from roboprobe.core.types import CampaignStatus
from roboprobe.runner.alerts import (
    ALERT_DISK_LOW,
    ALERT_GP_FALLBACK_REPEATED,
    ALERT_INFRA_UNHEALTHY,
    ALERT_NO_WORKERS,
    AlertEvaluator,
)
from roboprobe.runner.lifecycle import CampaignService
from roboprobe.store.records import CampaignRecord, SpaceRecord, SutProfileRecord

pytestmark = pytest.mark.unit


def test_no_workers_and_disk_and_fallback(tmp_path: Path) -> None:
    runner = RunnerSettings()
    storage = StorageSettings(artifact_root=tmp_path, min_free_gb=1000.0)
    ev = AlertEvaluator(runner, storage, free_gb_probe=lambda _p: 0.5)
    cid = uuid4()
    now = datetime(2020, 1, 1, tzinfo=UTC)
    assert (
        ev.no_workers(
            campaign_id=cid, running_since=now, now=now + timedelta(seconds=30), online_workers=0
        )
        is None
    )
    alert = ev.no_workers(
        campaign_id=cid, running_since=now, now=now + timedelta(seconds=60), online_workers=0
    )
    assert alert is not None and alert.code == ALERT_NO_WORKERS
    disk = ev.disk_low()
    assert disk is not None and disk.code == ALERT_DISK_LOW
    assert ev.gp_fallback_repeated(campaign_id=cid, consecutive_fallbacks=2) is None
    gp = ev.gp_fallback_repeated(campaign_id=cid, consecutive_fallbacks=3)
    assert gp is not None and gp.code == ALERT_GP_FALLBACK_REPEATED


def test_auto_pause_emits_alert_and_status_reason() -> None:
    uow = InMemoryUnitOfWork()
    cid = uuid4()
    with uow:
        uow.sut_profiles.add(
            SutProfileRecord(id="sut", backend="fake", config={}, config_hash="c" * 16)
        )
        uow.spaces.add(SpaceRecord(id="s", version="v", name="n", definition={}))
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
                budget=10,
                oracle_config={},
                status=CampaignStatus.RUNNING,
            )
        )
        uow.commit()
    svc = CampaignService(lambda: uow)
    alert = AlertEvaluator(RunnerSettings(), StorageSettings()).infra_unhealthy(
        campaign_id=cid, reason="invalid_ratio"
    )
    assert alert.code == ALERT_INFRA_UNHEALTHY
    status = svc.pause(cid, reason=alert.code)
    assert status is CampaignStatus.PAUSED
    with uow:
        camp = uow.campaigns.get(cid)
        assert camp is not None
        assert camp.status_reason == ALERT_INFRA_UNHEALTHY
        uow.events.append("alert", alert.payload(), campaign_id=cid)
        uow.commit()
        topics = [e.topic for e in uow.events.since(0)]
        assert "alert" in topics
