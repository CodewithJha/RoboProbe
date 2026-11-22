"""Restore registered campaign spaces and pins (T-081b, FR-SCN-001)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

import yaml

from roboprobe.core.errors import ValidationError
from roboprobe.core.types import JsonValue
from roboprobe.runner.ports import SpaceView
from roboprobe.scenario.space import ScenarioSpace

__all__ = ["load_campaign_space"]


class _CampaignReference(Protocol):
    @property
    def space_id(self) -> str: ...
    @property
    def space_version(self) -> str: ...
    @property
    def pins(self) -> Mapping[str, JsonValue]: ...


class _SpaceReader(Protocol):
    def get(self, space_id: str, version: str) -> SpaceView | None: ...


class _SpaceUow(Protocol):
    @property
    def spaces(self) -> _SpaceReader: ...


def load_campaign_space(
    uow: _SpaceUow, campaign: _CampaignReference, *, root: Path
) -> ScenarioSpace:
    """Prefer the immutable registered definition; retain shipped-file fallback for legacy rows."""
    record = uow.spaces.get(campaign.space_id, campaign.space_version)
    if record is not None and record.definition:
        space = ScenarioSpace.from_text(
            yaml.safe_dump(record.definition), source="registered campaign space", base_dir=root
        )
    else:
        space = ScenarioSpace.from_yaml(
            root / "configs/scenario_spaces" / f"{campaign.space_id}.yaml", base_dir=root
        )
    if (
        record is not None
        and record.definition
        and (space.id != campaign.space_id or space.version != campaign.space_version)
    ):
        msg = "registered space content does not match its immutable version"
        raise ValidationError(msg)
    return space.with_pins(campaign.pins)
