"""Immutable persistence records returned by repositories (never ORM instances).

Layer: Adapter (infrastructure).
Implements: T-011a, T-011b
"""

# ruff: noqa: D101, D102

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from roboprobe.core.types import CampaignStatus, FailureClass, RunStatus, Verdict
from roboprobe.store.orm import ARTIFACT_KINDS

__all__ = [
    "AnalysisRecord",
    "ArtifactRecord",
    "CampaignRecord",
    "ClaimedRun",
    "EventRecord",
    "ExperimentRecord",
    "FailureModeMemberRecord",
    "FailureModeRecord",
    "NewRun",
    "OracleResultRecord",
    "RiskMapRecord",
    "RunRecord",
    "SpaceRecord",
    "StrategyStateRecord",
    "SutProfileRecord",
    "WorkerRecord",
]


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SpaceRecord(_Record):
    id: str
    version: str
    name: str
    definition: dict[str, JsonValue]
    schema_version: int = 1
    created_at: datetime | None = None


class SutProfileRecord(_Record):
    id: str
    backend: str
    config: dict[str, JsonValue]
    config_hash: str
    created_at: datetime | None = None


class ExperimentRecord(_Record):
    notes: str = ""
    etag_version: int = 1
    id: UUID
    name: str
    design: dict[str, JsonValue]
    status: str
    results: dict[str, JsonValue] | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None


class CampaignRecord(_Record):
    id: UUID
    name: str
    space_id: str
    space_version: str
    sut_profile_id: str
    backend: str
    strategy_id: str
    strategy_params: dict[str, JsonValue] = Field(default_factory=dict)
    seed: int
    budget: int
    repeats: int = 1
    batch_size: int = 1
    pins: dict[str, JsonValue] = Field(default_factory=dict)
    oracle_config: dict[str, JsonValue]
    stop_rules: dict[str, JsonValue] = Field(default_factory=dict)
    status: CampaignStatus
    status_reason: str | None = None
    experiment_id: UUID | None = None
    experiment_rep: int | None = None
    tags: tuple[str, ...] = ()
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class NewRun(_Record):
    """Fields required to enqueue a run (id assigned on insert if omitted)."""

    campaign_id: UUID
    ordinal: int
    repeat_index: int = 0
    backend: str
    scenario_hash: str
    scenario_values: dict[str, JsonValue]
    x_unit: tuple[float, ...]
    seed: int
    phase: str
    proposal: dict[str, JsonValue] = Field(default_factory=dict)
    tags: tuple[str, ...] = ()
    replay_of: UUID | None = None
    priority: int = 100
    id: UUID | None = None


class RunRecord(_Record):
    id: UUID
    campaign_id: UUID
    ordinal: int
    repeat_index: int
    backend: str
    scenario_hash: str
    scenario_values: dict[str, JsonValue]
    x_unit: tuple[float, ...]
    seed: int
    phase: str
    proposal: dict[str, JsonValue]
    tags: tuple[str, ...]
    replay_of: UUID | None
    status: RunStatus
    priority: int
    attempt: int
    worker_id: str | None
    verdict: Verdict | None
    robustness: float | None
    primary_failure: str | None
    warnings: tuple[str, ...]
    metrics: dict[str, JsonValue]
    infra_error: str | None
    manifest: dict[str, JsonValue] | None
    enqueued_at: datetime | None = None
    claimed_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class OracleResultRecord(_Record):
    run_id: UUID
    oracle_id: str
    failure_class: FailureClass | str
    severity: str
    violated: bool
    robustness: float
    first_violation_t: float | None = None
    details: dict[str, JsonValue] = Field(default_factory=dict)


class StrategyStateRecord(_Record):
    campaign_id: UUID
    n_obs: int
    state: dict[str, JsonValue]
    updated_at: datetime | None = None


class AnalysisRecord(_Record):
    id: UUID
    campaign_id: UUID
    kind: str
    status: str
    n_runs: int
    summary: dict[str, JsonValue] | None = None
    report_sha256: str | None = None
    analysis_schema_version: int = 1
    created_at: datetime | None = None
    finished_at: datetime | None = None


class FailureModeMemberRecord(_Record):
    mode_id: UUID
    run_id: UUID
    membership: float


class FailureModeRecord(_Record):
    id: UUID
    campaign_id: UUID
    code: str
    label: str
    label_is_user: bool = False
    etag_version: int = 1
    duplicate_of: str | None = None
    primary_class: str
    class_mix: dict[str, JsonValue]
    size: int
    param_ranges: dict[str, JsonValue]
    characteristic: tuple[str, ...]
    medoid_run_id: UUID | None = None
    minimal_run_id: UUID | None = None
    rules: list[Any] = Field(default_factory=list)
    interaction: dict[str, JsonValue] | None = None
    reproducibility: float | None = None
    status: str = "open"
    first_seen_run: UUID | None = None
    analysis_id: UUID | None = None
    updated_at: datetime | None = None


class RiskMapRecord(_Record):
    id: UUID
    campaign_id: UUID
    analysis_id: UUID | None = None
    n_obs: int
    thresholds: dict[str, JsonValue]
    volumes: dict[str, JsonValue]
    robustness_score: float
    slices_artifact: UUID | None = None
    created_at: datetime | None = None


class ArtifactRecord(_Record):
    id: UUID
    run_id: UUID | None
    campaign_id: UUID | None
    kind: str
    sha256: str
    size_bytes: int
    rel_path: str
    media_type: str
    created_at: datetime | None = None

    def model_post_init(self, __context: object) -> None:
        if self.kind not in ARTIFACT_KINDS:
            msg = f"unknown artifact kind {self.kind!r}"
            raise ValueError(msg)


class WorkerRecord(_Record):
    id: str
    backend: str
    status: str
    capabilities: dict[str, JsonValue]
    version: str
    current_run_id: UUID | None = None
    started_at: datetime | None = None
    last_heartbeat: datetime | None = None


class EventRecord(_Record):
    id: int
    topic: str
    campaign_id: UUID | None
    payload: dict[str, JsonValue]
    created_at: datetime | None = None


class ClaimedRun(_Record):
    """A run claimed from the queue (docs/05 §13)."""

    run_id: UUID
    campaign_id: UUID
    scenario_hash: str
    scenario_values: dict[str, JsonValue]
    seed: int
    attempt: int
    backend: str
    ordinal: int
    worker_id: str
    wall_timeout_s: float
    sim_time_budget_s: float
