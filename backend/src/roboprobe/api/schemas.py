"""REST DTOs (docs/12 §3). Never expose ORM rows.

Implements: T-081, T-082, T-084
"""

# ruff: noqa: D101

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from roboprobe.core.types import CampaignStatus, JsonValue
from roboprobe.runner.campaign_spec import CampaignCreate, SpaceRef, StrategyRef

__all__ = [
    "ArtifactOut",
    "CampaignCreate",
    "CampaignOut",
    "CampaignPatch",
    "CampaignProgress",
    "ExperimentComparisonOut",
    "ExperimentCreate",
    "ExperimentNotes",
    "ExperimentOut",
    "FailureModeOut",
    "FailureModePatch",
    "ImportanceOut",
    "ManualRunCreate",
    "Page",
    "ReplayRequest",
    "ReportCreate",
    "ReportJobOut",
    "RiskOut",
    "RiskSliceOut",
    "RunOut",
    "SpaceOut",
    "SpaceRef",
    "StrategyRef",
    "SutProfileCreate",
    "SutProfileOut",
    "TraceOut",
    "WorkerOut",
]


class Page[T](BaseModel):
    """Cursor page wrapper."""

    model_config = ConfigDict(extra="forbid")

    items: list[T]
    next_cursor: str | None = None


class CampaignPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    tags: list[str] | None = None


class CampaignOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    status: CampaignStatus
    backend: str
    strategy: StrategyRef
    space: SpaceRef | None = None
    pins: dict[str, JsonValue] = Field(default_factory=dict)
    oracle_config: dict[str, JsonValue] = Field(default_factory=dict)
    budget: int
    repeats: int
    batch_size: int
    counts: dict[str, int] = Field(default_factory=dict)
    modes_found: int = 0
    first_failure_at: int | None = None
    warnings: list[dict[str, JsonValue]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    links: dict[str, str] = Field(default_factory=dict)


class CampaignProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID
    counts: dict[str, int]
    discovery_curve: list[dict[str, JsonValue]] = Field(default_factory=list)


class TraceOut(BaseModel):
    """Event-preserving trace samples (T-081e; docs/12 §3.9)."""

    model_config = ConfigDict(extra="forbid")
    t: list[float]
    columns: dict[str, list[JsonValue]]
    hz: float
    source_hz: float | None
    truncated: bool


class RunOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    campaign_id: UUID
    ordinal: int
    repeat_index: int
    status: str
    phase: str
    scenario: dict[str, JsonValue]
    proposal: dict[str, JsonValue] = Field(default_factory=dict)
    seed: int
    verdict: str | None = None
    robustness: float | None = None
    primary_failure: str | None = None
    warnings: list[str] = Field(default_factory=list)
    oracles: list[dict[str, JsonValue]] = Field(default_factory=list)
    metrics: dict[str, JsonValue] = Field(default_factory=dict)
    worker_id: str | None = None
    infra_error: str | None = None
    timing: dict[str, datetime | None] = Field(default_factory=dict)
    mode: dict[str, JsonValue] | None = None
    manifest: dict[str, JsonValue] | None = None
    tags: list[str] = Field(default_factory=list)


class ManualRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, JsonValue]
    repeats: int = Field(default=1, gt=0)
    tags: list[str] = Field(default_factory=list)


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repeats: int = 1
    fresh_seeds: bool = False


class SpaceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: str
    name: str
    schema_version: int
    created_at: datetime | None = None


class SutProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    backend: str
    config: dict[str, JsonValue] = Field(default_factory=dict)


class SutProfileOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    backend: str
    config_hash: str
    created_at: datetime | None = None


class FailureModeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    campaign_id: UUID
    code: str
    label: str
    label_is_user: bool = False
    version: int = 1
    duplicate_of: str | None = None
    param_ranges: dict[str, JsonValue] = Field(default_factory=dict)
    characteristic: list[str] = Field(default_factory=list)
    rules: list[JsonValue] = Field(default_factory=list)
    medoid_run_id: UUID | None = None
    minimal_run_id: UUID | None = None
    size: int
    primary_class: str
    status: str
    interaction: dict[str, JsonValue] | None = None


_MODE_LABEL_MAX_LENGTH = 80
_MODE_STATUSES = frozenset({"open", "accepted", "fixed", "duplicate"})


class FailureModePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = None
    status: str | None = None
    duplicate_of: str | None = None

    @field_validator("label")
    @classmethod
    def _label(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not 1 <= len(value) <= _MODE_LABEL_MAX_LENGTH or not value.isprintable():
                msg = f"label must use 1 to {_MODE_LABEL_MAX_LENGTH} characters"
                raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _duplicate(self) -> Self:
        if self.status is not None and self.status not in _MODE_STATUSES:
            msg = "unknown failure mode status"
            raise ValueError(msg)
        if self.status == "duplicate" and not self.duplicate_of:
            msg = "duplicate status requires duplicate_of"
            raise ValueError(msg)
        return self


class ImportanceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID
    analysis_id: UUID | None = None
    importance: dict[str, JsonValue] | None = None
    interactions: dict[str, JsonValue] | None = None
    rules: list[JsonValue] = Field(default_factory=list)


class RiskOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID
    analysis_id: UUID | None = None
    computed_at: datetime | None = None
    robustness_score: float | None = None
    volumes: dict[str, JsonValue] = Field(default_factory=dict)
    thresholds: dict[str, JsonValue] = Field(default_factory=dict)


class RiskSliceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x_param: str
    y_param: str
    anchor: str
    resolution: int
    grid: dict[str, JsonValue] = Field(default_factory=dict)
    x_values: list[float] = Field(default_factory=list)
    y_values: list[float] = Field(default_factory=list)
    p_fail: list[list[float]] = Field(default_factory=list)
    region: list[list[int]] = Field(default_factory=list)
    log_x: bool = False
    log_y: bool = False
    points: list[dict[str, JsonValue]] = Field(default_factory=list)


class ExperimentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    design: dict[str, JsonValue]


class ExperimentNotes(BaseModel):
    """Editable threats-to-validity notes (T-112b)."""

    model_config = ConfigDict(extra="forbid")
    notes: str


class ExperimentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: str = ""
    version: int = 1
    cells: list[dict[str, JsonValue]] = Field(default_factory=list)

    id: UUID
    name: str
    status: str
    design: dict[str, JsonValue]
    results: dict[str, JsonValue] | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None


class ExperimentComparisonOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: UUID
    metrics: list[str] = Field(default_factory=list)
    strategies: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)
    tests: list[dict[str, JsonValue]] = Field(default_factory=list)


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    id: UUID


class ReportJobOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: str
    kind: str
    target_id: UUID
    artifact_id: UUID | None = None
    report_id: UUID | None = None
    status_url: str | None = None


class ArtifactOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    kind: str
    sha256: str
    size_bytes: int
    media_type: str


class WorkerOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    backend: str
    status: str
    version: str
    last_heartbeat: datetime | None = None
    heartbeat_age_s: float | None = None
    current_run_id: UUID | None = None
    host_hash: str | None = None
