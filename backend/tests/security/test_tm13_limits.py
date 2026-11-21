"""TM-13: campaign budget and batch size cannot exceed runner caps (T-109)."""

from __future__ import annotations

from pathlib import Path

import pytest

from roboprobe.cli.campaign import create_campaign_from_config
from roboprobe.core.errors import ValidationError
from roboprobe.core.settings import RoboProbeSettings

pytestmark = pytest.mark.security


def test_budget_above_cap_rejected(tmp_path: Path) -> None:
    campaign = tmp_path / "campaign.yaml"
    campaign.write_text(
        "schema_version: 1\nspace: {id: warehouse_v1}\nbackend: kinematic2d\n"
        "strategy: {id: S-RANDOM}\nbudget: 100000\n",
        encoding="utf-8",
    )
    settings = RoboProbeSettings(
        storage={"workdir_root": str(tmp_path / "w"), "artifact_root": str(tmp_path / "a")},
        runner={"max_budget": 50},
    )
    with pytest.raises(ValidationError, match="max_budget"):
        create_campaign_from_config(campaign, settings)
