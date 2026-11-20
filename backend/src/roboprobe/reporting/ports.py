"""Structural ports for offline reports (no ``roboprobe.store`` import).

Layer: Application (L3).

Implements: T-078b, T-079, docs/16 §2
"""

# ruff: noqa: D101, D102, D105

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import Protocol
from uuid import UUID

from roboprobe.core.types import JsonValue

__all__ = [
    "ReportAnalysisRow",
    "ReportArtifactStore",
    "ReportCampaignRow",
    "ReportExperimentRow",
    "ReportModeRow",
    "ReportRunRow",
    "ReportUnitOfWork",
]


class ReportRunRow(Protocol):
    """Run fields report renderers read."""

    id: UUID
    ordinal: int
    repeat_index: int
    verdict: object
    metrics: Mapping[str, JsonValue] | None
    x_unit: Sequence[float] | None
    phase: object
    tags: Sequence[object] | None


class _ReportPage(Protocol):
    items: Sequence[ReportRunRow]
    next_cursor: str | None


class ReportCampaignRow(Protocol):
    id: UUID
    name: object
    backend: object
    strategy_id: object
    budget: int
    seed: int
    status: object
    experiment_rep: int | None
    tags: Sequence[object] | None


class ReportExperimentRow(Protocol):
    name: object
    design: Mapping[str, JsonValue]
    results: Mapping[str, JsonValue] | None


class ReportModeRow(Protocol):
    code: str
    label: str
    size: int
    primary_class: object
    class_mix: object
    rules: Sequence[Mapping[str, object]] | None
    interaction: Mapping[str, object] | None
    medoid_run_id: UUID | None
    minimal_run_id: UUID | None


class ReportAnalysisRow(Protocol):
    summary: Mapping[str, object]


class _RiskMapRow(Protocol):
    slices_artifact: object | None


class _ArtifactRow(Protocol):
    sha256: object
    rel_path: object


class _RunsRepo(Protocol):
    def list_for_campaign(
        self, campaign_id: UUID, *, limit: int | None = None, cursor: str | None = None
    ) -> _ReportPage: ...


class _CampaignsRepo(Protocol):
    def get(self, campaign_id: UUID) -> ReportCampaignRow | None: ...

    def list_for_experiment(self, experiment_id: UUID) -> Sequence[ReportCampaignRow]: ...


class _ExperimentsRepo(Protocol):
    def get(self, experiment_id: UUID) -> ReportExperimentRow | None: ...


class _ModesRepo(Protocol):
    def list_for_campaign(self, campaign_id: UUID) -> Sequence[ReportModeRow]: ...


class _AnalysesRepo(Protocol):
    def list_for_campaign(self, campaign_id: UUID) -> Sequence[ReportAnalysisRow]: ...


class _RiskMapsRepo(Protocol):
    def latest(self, campaign_id: UUID) -> _RiskMapRow | None: ...


class _ArtifactsRepo(Protocol):
    def get(self, artifact_id: object) -> _ArtifactRow | None: ...


class ReportUnitOfWork(Protocol):
    """UoW surface used by campaign and experiment HTML reports."""

    campaigns: _CampaignsRepo
    experiments: _ExperimentsRepo
    runs: _RunsRepo
    modes: _ModesRepo
    analyses: _AnalysesRepo
    risk_maps: _RiskMapsRepo
    artifacts: _ArtifactsRepo

    def __enter__(self) -> ReportUnitOfWork: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...


class ReportArtifactStore(Protocol):
    """Artefact store used when embedding / attaching report assets."""

    def put(
        self,
        src: Path,
        kind: str,
        *,
        run_id: UUID | None = None,
        campaign_id: UUID | None = None,
    ) -> object: ...

    def path(self, ref: object) -> Path: ...
