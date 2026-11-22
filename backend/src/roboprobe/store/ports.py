"""Repository and Unit-of-Work ports (docs/05 §9). Implementations live beside this module.

Layer: Adapter (infrastructure). Domain code depends on these Protocols via bootstrap.
Implements: T-011a, T-011b, T-011c, T-012
"""

# ruff: noqa: D102, D105

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from types import TracebackType
from typing import Protocol
from uuid import UUID

from roboprobe.core.types import CampaignStatus, JsonValue, Observation, RunOutcome
from roboprobe.store.pagination import Page
from roboprobe.store.records import (
    AnalysisRecord,
    ArtifactRecord,
    CampaignRecord,
    ClaimedRun,
    EventRecord,
    ExperimentRecord,
    FailureModeMemberRecord,
    FailureModeRecord,
    NewRun,
    OracleResultRecord,
    RiskMapRecord,
    RunRecord,
    SpaceRecord,
    StrategyStateRecord,
    SutProfileRecord,
    WorkerRecord,
)

__all__ = [
    "AnalysisRepo",
    "ArtifactRepo",
    "CampaignRepo",
    "EventRepo",
    "ExperimentRepo",
    "FailureModeRepo",
    "OracleResultRepo",
    "RiskMapRepo",
    "RunQueue",
    "RunRepo",
    "SpaceRepo",
    "StrategyStateRepo",
    "SutProfileRepo",
    "UnitOfWork",
    "WorkerRepo",
]


class SpaceRepo(Protocol):
    """Scenario space versions. Pre: ``(id, version)`` is unique. Post: ``get`` returns the row."""

    def get(self, space_id: str, version: str) -> SpaceRecord | None: ...

    def add(self, record: SpaceRecord) -> None: ...

    def list(self, *, limit: int | None = None, cursor: str | None = None) -> Page[SpaceRecord]: ...


class SutProfileRepo(Protocol):
    """SUT profiles keyed by id."""

    def get(self, profile_id: str) -> SutProfileRecord | None: ...

    def add(self, record: SutProfileRecord) -> None: ...

    def list(
        self, *, limit: int | None = None, cursor: str | None = None
    ) -> Page[SutProfileRecord]: ...


class CampaignRepo(Protocol):
    """Campaign aggregate."""

    def get(self, campaign_id: UUID) -> CampaignRecord | None: ...

    def add(self, record: CampaignRecord) -> None: ...

    def set_status(
        self, campaign_id: UUID, status: CampaignStatus, *, reason: str | None = None
    ) -> None: ...

    def list(
        self, *, limit: int | None = None, cursor: str | None = None
    ) -> Page[CampaignRecord]: ...

    def list_for_experiment(self, experiment_id: UUID) -> tuple[CampaignRecord, ...]: ...


class RunRepo(Protocol):
    """Runs. ``insert_batch`` is idempotent on ``(campaign_id, ordinal, repeat_index)``."""

    def get(self, run_id: UUID) -> RunRecord | None: ...

    def insert_batch(self, runs: Sequence[NewRun]) -> tuple[UUID, ...]: ...

    def import_many(self, runs: Sequence[RunRecord]) -> None:
        """Insert full run rows (bundle import). Pre: ids and campaign exist; no collisions."""
        ...

    def list_for_campaign(
        self, campaign_id: UUID, *, limit: int | None = None, cursor: str | None = None
    ) -> Page[RunRecord]: ...

    def history(
        self,
        campaign_id: UUID,
        *,
        exclude_phases: frozenset[str] | None = None,
    ) -> list[Observation]:
        r"""Finished non-INVALID runs ordered by ordinal (single query).

        ``exclude_phases`` defaults to ``{\"confirm\", \"manual\"}`` so strategy
        history and MET metrics ignore confirmatory / ad-hoc runs (docs/09 §6).
        """
        ...

    def cancel_pending(self, campaign_id: UUID) -> int:
        """Mark all ``PENDING`` runs for ``campaign_id`` as ``CANCELLED``; return count."""
        ...


class OracleResultRepo(Protocol):
    """Per-run oracle rows, replaced as a set when a verdict is persisted."""

    def replace_for_run(self, run_id: UUID, results: Sequence[OracleResultRecord]) -> None: ...

    def list_for_run(self, run_id: UUID) -> tuple[OracleResultRecord, ...]: ...


class StrategyStateRepo(Protocol):
    """Strategy checkpoint per campaign."""

    def get(self, campaign_id: UUID) -> StrategyStateRecord | None: ...

    def upsert(self, record: StrategyStateRecord) -> None: ...


class FailureModeRepo(Protocol):
    """Failure modes and members. Upsert preserves ``label_is_user`` labels."""

    def get(self, mode_id: UUID, *, for_update: bool = False) -> FailureModeRecord | None: ...

    def set_interaction(self, mode_id: UUID, interaction: dict[str, JsonValue]) -> None: ...

    def list_for_campaign(self, campaign_id: UUID) -> tuple[FailureModeRecord, ...]: ...

    def upsert_modes(
        self,
        campaign_id: UUID,
        modes: Sequence[FailureModeRecord],
        members: Sequence[FailureModeMemberRecord],
    ) -> None: ...


class RiskMapRepo(Protocol):
    """Risk maps."""

    def add(self, record: RiskMapRecord) -> None: ...

    def latest(self, campaign_id: UUID) -> RiskMapRecord | None: ...


class AnalysisRepo(Protocol):
    """Analysis jobs."""

    def get(self, analysis_id: UUID) -> AnalysisRecord | None: ...

    def add(self, record: AnalysisRecord) -> None: ...

    def list_for_campaign(self, campaign_id: UUID) -> tuple[AnalysisRecord, ...]: ...


class ExperimentRepo(Protocol):
    """Experiments grouping campaigns."""

    def get(self, experiment_id: UUID) -> ExperimentRecord | None: ...

    def add(self, record: ExperimentRecord) -> None: ...

    def set_status(self, experiment_id: UUID, status: str) -> None: ...

    def set_results(self, experiment_id: UUID, results: dict[str, JsonValue]) -> None: ...

    def patch_notes(self, experiment_id: UUID, notes: str, expected_etag: int) -> None: ...

    def list(
        self, *, limit: int | None = None, cursor: str | None = None
    ) -> Page[ExperimentRecord]: ...


class WorkerRepo(Protocol):
    """Workers keyed by ``<prefix>:<pid>:<slot>``."""

    def get(self, worker_id: str) -> WorkerRecord | None: ...

    def register(self, record: WorkerRecord) -> None: ...

    def heartbeat(self, worker_id: str, *, at: datetime) -> None: ...

    def set_status(
        self, worker_id: str, status: str, *, current_run_id: UUID | None = None
    ) -> None: ...

    def online(self, backend: str) -> tuple[WorkerRecord, ...]: ...

    def stale(self, *, older_than: datetime) -> tuple[WorkerRecord, ...]:
        """Workers whose ``last_heartbeat`` is strictly before ``older_than`` (or missing)."""
        ...


class ArtifactRepo(Protocol):
    """Artefact metadata rows."""

    def add(self, record: ArtifactRecord) -> None: ...

    def get(self, artifact_id: UUID) -> ArtifactRecord | None: ...

    def list_for_run(self, run_id: UUID) -> tuple[ArtifactRecord, ...]: ...

    def sha256_set(self) -> frozenset[str]: ...

    def delete(self, artifact_id: UUID) -> None: ...

    def bags_for_retention(self) -> tuple[ArtifactRecord, ...]: ...


class EventRepo(Protocol):
    """Transactional outbox."""

    def append(
        self, topic: str, payload: Mapping[str, JsonValue], *, campaign_id: UUID | None = None
    ) -> int: ...

    def since(
        self, last_id: int, *, campaign_id: UUID | None = None, limit: int | None = None
    ) -> tuple[EventRecord, ...]: ...


class RunQueue(Protocol):
    """Claim/complete/reap port (docs/11 §4). Lives here so ``store`` does not import ``runner``."""

    def claim(self, worker_id: str, backend: str) -> ClaimedRun | None: ...

    def mark_running(self, run_id: UUID) -> None: ...

    def mark_evaluating(self, run_id: UUID) -> None: ...

    def complete(
        self, run_id: UUID, outcome: RunOutcome, *, manifest: dict[str, JsonValue] | None = None
    ) -> None: ...

    def fail(self, run_id: UUID, infra_error: str) -> None: ...

    def reap(self, now: datetime, heartbeat_timeout_s: float, max_attempts: int) -> int: ...

    def depth(self, backend: str) -> int: ...


class UnitOfWork(Protocol):
    """One session / one transaction. Pre: entered. Post: commit or rollback, session closed."""

    spaces: SpaceRepo
    sut_profiles: SutProfileRepo
    campaigns: CampaignRepo
    runs: RunRepo
    oracle_results: OracleResultRepo
    strategy_states: StrategyStateRepo
    modes: FailureModeRepo
    risk_maps: RiskMapRepo
    analyses: AnalysisRepo
    experiments: ExperimentRepo
    workers: WorkerRepo
    artifacts: ArtifactRepo
    events: EventRepo

    def __enter__(self) -> UnitOfWork: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def notify(self, channel: str, payload: str) -> None: ...

    def try_advisory_lock(self, key: str) -> bool:
        """Acquire a session-scoped advisory lock for ``key`` (non-blocking)."""
        ...

    def advisory_unlock(self, key: str) -> None:
        """Release a previously acquired advisory lock for ``key``."""
        ...
