"""Shared campaign input contract for CLI and HTTP (T-081b, FR-API-001)."""

# ruff: noqa: D101
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from roboprobe.core.types import JsonValue

__all__ = ["CampaignCreate", "SpaceRef", "StrategyRef"]


class SpaceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: str | None = None


class StrategyRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    seed: int | None = None
    params: dict[str, JsonValue] = Field(default_factory=dict)


class CampaignCreate(BaseModel):
    """``CampaignCreate`` (docs/12 §3.1)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    space: SpaceRef
    sut_profile_id: str | None = None
    backend: str
    strategy: StrategyRef
    budget: int
    repeats: int = 1
    batch_size: int = 1
    pins: dict[str, JsonValue] = Field(default_factory=dict)
    oracle_overrides: dict[str, JsonValue] = Field(default_factory=dict)
    stop_rules: dict[str, JsonValue] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    start: bool = False
