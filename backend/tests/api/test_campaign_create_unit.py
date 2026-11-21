"""Unit test for campaign_create against shipped configs."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from roboprobe.api.campaign_create import create_campaign
from roboprobe.api.schemas import CampaignCreate, SpaceRef, StrategyRef
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.runner.lifecycle import CampaignService
from roboprobe.scenario.repo_root import discover_repo_root

pytestmark = pytest.mark.unit


class _Campaigns:
    def __init__(self) -> None:
        self.rows: list[object] = []

    def add(self, row: object) -> None:
        self.rows.append(row)

    def get(self, cid: UUID) -> object | None:
        for row in self.rows:
            if row.id == cid:  # type: ignore[attr-defined]
                return row
        return None


class _Spaces:
    def __init__(self) -> None:
        self.rows: list[object] = []

    def get(self, sid: str, version: str) -> object | None:
        for row in self.rows:
            if row.id == sid and row.version == version:  # type: ignore[attr-defined]
                return row
        return None

    def add(self, row: object) -> None:
        self.rows.append(row)


class _Sut:
    def get(self, pid: str) -> object | None:
        return object() if pid == "k2d_default" else None

    def add(self, _: object) -> None:
        return None


class _Uow:
    def __init__(self) -> None:
        self.campaigns = _Campaigns()
        self.spaces = _Spaces()
        self.sut_profiles = _Sut()

    def commit(self) -> None:
        return None


def test_create_campaign_registers_space(tmp_path: Path) -> None:
    root = discover_repo_root()
    if not (root / "configs" / "scenario_spaces" / "warehouse_v1.yaml").is_file():
        pytest.skip("shipped space missing")
    settings = RoboProbeSettings(
        storage={"workdir_root": str(tmp_path / "w"), "artifact_root": str(tmp_path / "a")}
    )
    uow = _Uow()
    body = CampaignCreate(
        space=SpaceRef(id="warehouse_v1"),
        backend="kinematic2d",
        strategy=StrategyRef(id="S-RANDOM", seed=42),
        budget=5,
        batch_size=1,
        sut_profile_id="k2d_default",
    )
    # Pre-register sut file exists in repo — create_campaign reads profile from disk
    cid = create_campaign(
        body,
        uow=uow,
        settings=settings,
        campaigns=CampaignService(lambda: uow),
        space_root=root,
    )
    assert isinstance(cid, UUID)
    assert uow.campaigns.get(cid) is not None
