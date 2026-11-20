# ruff: noqa: D101, D102, D105

"""Ports the runner depends on (injected; never import ``roboprobe.store`` / ``backends``).

Layer: Application (L3). Structural Protocols match store/backends adapters.
Implements: docs/16 §2, ADR-0016
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Protocol
from uuid import UUID

from roboprobe.core.types import (
    CampaignStatus,
    JsonValue,
    Observation,
    RunOutcome,
    Scenario,
    SutProfile,
    TaskSpec,
    Trace,
)

__all__ = [
    "ArtifactRefView",
    "ArtifactRepoPort",
    "ArtifactStorePort",
    "CampaignRepoPort",
    "CampaignView",
    "ClaimedRunView",
    "EpisodeRequestView",
    "EpisodeResultView",
    "EventRepoPort",
    "ExperimentRepoPort",
    "FailureModeRepoPort",
    "FailureModeView",
    "MaterializedScenarioView",
    "NewRunView",
    "RunQueuePort",
    "RunRepoPort",
    "RunView",
    "SimulatorBackendPort",
    "StrategyStateRepoPort",
    "StrategyStateView",
    "SutProfileRepoPort",
    "UnitOfWorkPort",
    "UowFactory",
    "WorkerRepoPort",
    "WorkerView",
]


class CampaignView(Protocol):
    """Campaign aggregate fields the runner reads."""

    id: UUID
    name: str
    space_id: str
    space_version: str
    sut_profile_id: str
    backend: str
    strategy_id: str
    strategy_params: dict[str, JsonValue]
    seed: int
    budget: int
    repeats: int
    batch_size: int
    pins: dict[str, JsonValue]
    oracle_config: dict[str, JsonValue]
    stop_rules: dict[str, JsonValue]
    status: CampaignStatus
    status_reason: str | None
    started_at: datetime | None
    finished_at: datetime | None


class RunView(Protocol):
    """Run row fields the runner reads."""

    id: UUID
    campaign_id: UUID
    ordinal: int
    repeat_index: int
    status: object
    verdict: object
    x_unit: tuple[float, ...]
    scenario_values: dict[str, JsonValue]
    scenario_hash: str
    phase: str
    proposal: dict[str, JsonValue]
    seed: int
    backend: str
    attempt: int
    worker_id: str | None
    metrics: Mapping[str, object] | None
    tags: Sequence[object]
    primary_failure: object
    robustness: float | None


class ClaimedRunView(Protocol):
    """Queue claim payload."""

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


class WorkerView(Protocol):
    """Worker row."""

    id: str
    backend: str
    status: str
    capabilities: dict[str, JsonValue]
    version: str
    current_run_id: UUID | None
    last_heartbeat: datetime | None


class StrategyStateView(Protocol):
    """Strategy checkpoint row."""

    campaign_id: UUID
    n_obs: int
    state: dict[str, JsonValue]


class NewRunView(Protocol):
    """Fields required to enqueue a run (structural)."""

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


class ArtifactRefView(Protocol):
    """Artefact store put result."""

    id: UUID
    sha256: str
    rel_path: str
    kind: str
    size_bytes: int
    media_type: str
    run_id: UUID | None
    campaign_id: UUID | None


class CampaignRepoPort(Protocol):
    def get(self, campaign_id: UUID) -> CampaignView | None: ...

    def add(self, record: object) -> None: ...

    def set_status(
        self, campaign_id: UUID, status: CampaignStatus, *, reason: str | None = None
    ) -> None: ...

    def list(self, *, limit: int | None = None, cursor: str | None = None) -> object: ...

    def list_for_experiment(self, experiment_id: UUID) -> Sequence[object]: ...


class _RunPage(Protocol):
    items: Sequence[RunView]
    next_cursor: str | None


class RunRepoPort(Protocol):
    def get(self, run_id: UUID) -> RunView | None: ...

    def insert_batch(self, runs: Sequence[object]) -> tuple[UUID, ...]: ...

    def list_for_campaign(
        self, campaign_id: UUID, *, limit: int | None = None, cursor: str | None = None
    ) -> _RunPage: ...

    def history(self, campaign_id: UUID) -> list[Observation]: ...

    def cancel_pending(self, campaign_id: UUID) -> int: ...


class EventRepoPort(Protocol):
    def append(
        self, topic: str, payload: Mapping[str, JsonValue], *, campaign_id: UUID | None = None
    ) -> int: ...


class WorkerRepoPort(Protocol):
    def get(self, worker_id: str) -> WorkerView | None: ...

    def register(self, record: object) -> None: ...

    def heartbeat(self, worker_id: str, *, at: datetime) -> None: ...

    def set_status(
        self, worker_id: str, status: str, *, current_run_id: UUID | None = None
    ) -> None: ...

    def online(self, backend: str) -> tuple[WorkerView, ...]: ...

    def stale(self, *, older_than: datetime) -> tuple[WorkerView, ...]: ...


class StrategyStateRepoPort(Protocol):
    def get(self, campaign_id: UUID) -> StrategyStateView | None: ...

    def upsert(self, record: object) -> None: ...


class SutProfileRepoPort(Protocol):
    def get(self, profile_id: str) -> object | None: ...


class ArtifactRepoPort(Protocol):
    def add(self, record: object) -> None: ...


class ExperimentRepoPort(Protocol):
    def get(self, experiment_id: UUID) -> object | None: ...

    def add(self, record: object) -> None: ...

    def set_status(self, experiment_id: UUID, status: str) -> None: ...

    def set_results(self, experiment_id: UUID, results: dict[str, JsonValue]) -> None: ...


class FailureModeView(Protocol):
    """Failure-mode fields confirmation and analysis orchestration read."""

    id: UUID
    campaign_id: UUID
    code: str
    size: int
    label: str
    primary_class: object
    class_mix: Mapping[str, object] | None
    characteristic: Sequence[object]
    param_ranges: Mapping[str, object] | None
    interaction: Mapping[str, JsonValue] | None
    medoid_run_id: UUID | None
    minimal_run_id: UUID | None

    def model_copy(self, *, update: Mapping[str, object]) -> FailureModeView: ...


class FailureModeRepoPort(Protocol):
    def get(self, mode_id: UUID) -> FailureModeView | None: ...

    def list_for_campaign(self, campaign_id: UUID) -> Sequence[FailureModeView]: ...

    def upsert_modes(
        self,
        campaign_id: UUID,
        modes: Sequence[FailureModeView],
        members: Sequence[object],
    ) -> None: ...


class UnitOfWorkPort(Protocol):
    """One session / one transaction."""

    campaigns: CampaignRepoPort
    runs: RunRepoPort
    events: EventRepoPort
    workers: WorkerRepoPort
    strategy_states: StrategyStateRepoPort
    sut_profiles: SutProfileRepoPort
    artifacts: ArtifactRepoPort
    oracle_results: object
    modes: FailureModeRepoPort
    experiments: ExperimentRepoPort
    analyses: object
    risk_maps: object

    def __enter__(self) -> UnitOfWorkPort: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def try_advisory_lock(self, key: str) -> bool: ...

    def advisory_unlock(self, key: str) -> None: ...


UowFactory = Callable[[], UnitOfWorkPort]


class RunQueuePort(Protocol):
    def claim(self, worker_id: str, backend: str) -> ClaimedRunView | None: ...

    def mark_running(self, run_id: UUID) -> None: ...

    def mark_evaluating(self, run_id: UUID) -> None: ...

    def complete(
        self, run_id: UUID, outcome: RunOutcome, *, manifest: dict[str, JsonValue] | None = None
    ) -> None: ...

    def fail(self, run_id: UUID, infra_error: str) -> None: ...

    def reap(self, now: datetime, heartbeat_timeout_s: float, max_attempts: int) -> int: ...

    def depth(self, backend: str) -> int: ...


class ArtifactStorePort(Protocol):
    def put(
        self,
        src: Path,
        kind: str,
        run_id: UUID | None = None,
        campaign_id: UUID | None = None,
    ) -> ArtifactRefView: ...


class MaterializedScenarioView(Protocol):
    files: dict[str, Path]
    payload: dict[str, JsonValue]


class EpisodeResultView(Protocol):
    trace: Trace
    artifacts: dict[str, Path]
    backend_meta: dict[str, str]
    infra_error: str | None


class EpisodeRequestView(Protocol):
    run_id: UUID
    scenario: Scenario
    task: TaskSpec
    sut_profile: SutProfile
    seed: int
    workdir: Path
    sim_time_budget_s: float
    wall_timeout_s: float
    record_bag: bool


class SimulatorBackendPort(Protocol):
    """Structural backend port (concrete class from ``roboprobe.backends``)."""

    @property
    def capabilities(self) -> object: ...

    def prepare(self) -> None: ...

    def materialize(self, req: object) -> MaterializedScenarioView: ...

    def run_episode(
        self,
        req: object,
        materialized: object,
        on_progress: Callable[[float], None] | None = None,
    ) -> EpisodeResultView: ...

    def cancel(self) -> None: ...

    def shutdown(self) -> None: ...
