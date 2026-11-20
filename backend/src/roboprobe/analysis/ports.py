"""Structural ports for analysis (no ``roboprobe.store`` import).

Layer: Domain (L2).

Implements: T-075a, docs/16 §2
"""

# ruff: noqa: D101, D102

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol
from uuid import UUID

from roboprobe.core.types import JsonValue

__all__ = [
    "AnalysisArtifactStore",
    "AnalysisCampaignRow",
    "AnalysisModeRow",
    "AnalysisRunRow",
    "AnalysisUnitOfWork",
    "ArtifactRefLike",
]


class AnalysisRunRow(Protocol):
    """Run fields the analysis pipeline reads."""

    id: UUID
    verdict: object
    phase: object
    primary_failure: object
    metrics: Mapping[str, JsonValue] | None
    scenario_values: Mapping[str, object] | None
    x_unit: Sequence[float]
    robustness: float | None


class _PageLike(Protocol):
    items: Sequence[AnalysisRunRow]
    next_cursor: str | None


class AnalysisCampaignRow(Protocol):
    space_id: str
    space_version: str
    seed: int
    backend: object


class AnalysisModeRow(Protocol):
    id: UUID
    code: str
    label: str
    label_is_user: bool
    status: object


class _RunsRepo(Protocol):
    def list_for_campaign(
        self, campaign_id: UUID, *, limit: int | None = None, cursor: str | None = None
    ) -> _PageLike: ...

    def get(self, run_id: UUID) -> AnalysisRunRow | None: ...


class _CampaignsRepo(Protocol):
    def get(self, campaign_id: UUID) -> AnalysisCampaignRow | None: ...


class _ModesRepo(Protocol):
    def list_for_campaign(self, campaign_id: UUID) -> Sequence[AnalysisModeRow]: ...

    def upsert_modes(
        self, campaign_id: UUID, modes: Sequence[object], members: Sequence[object]
    ) -> None: ...


class _AnalysesRepo(Protocol):
    def add(self, record: object) -> None: ...


class _EventsPort(Protocol):
    def append(
        self,
        topic: str,
        payload: Mapping[str, JsonValue],
        *,
        campaign_id: UUID | None = None,
    ) -> None: ...


class _RiskMapsPort(Protocol):
    def add(self, record: object) -> None: ...


class AnalysisUnitOfWork(Protocol):
    """UoW surface used by :func:`analyze_campaign`."""

    campaigns: _CampaignsRepo
    runs: _RunsRepo
    modes: _ModesRepo
    analyses: _AnalysesRepo
    risk_maps: _RiskMapsPort
    events: _EventsPort

    def commit(self) -> None: ...


class ArtifactRefLike(Protocol):
    sha256: str


class AnalysisArtifactStore(Protocol):
    """Content-addressed artefact store used when writing analysis outputs."""

    def put(
        self,
        src: Path,
        kind: str,
        *,
        run_id: UUID | None = None,
        campaign_id: UUID | None = None,
    ) -> ArtifactRefLike: ...
