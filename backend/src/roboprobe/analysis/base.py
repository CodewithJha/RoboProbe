"""Pluggable analysis steps and shared context (docs/05 §7, §13).

Implements: T-075a, FR-ANA-006
"""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from roboprobe.analysis.ports import AnalysisArtifactStore, AnalysisUnitOfWork
from roboprobe.analysis.types import (
    AnalysisRun,
    ClusteringResult,
    FailureModeSummary,
    FeatureMatrix,
    ImportanceReport,
    Rule,
)
from roboprobe.core.clock import Clock
from roboprobe.core.settings.analysis import AnalysisSettings, RiskSettings
from roboprobe.scenario.space import ScenarioSpace

__all__ = [
    "AnalysisContext",
    "AnalysisKind",
    "AnalysisReport",
    "Analyzer",
]


class AnalysisKind(StrEnum):
    """Which step chain to run."""

    FULL = "full"
    INCREMENTAL = "incremental"


@dataclass
class AnalysisReport:
    """Machine-readable campaign analysis result (``analysis_schema_version`` 1)."""

    analysis_id: UUID
    campaign_id: UUID
    kind: AnalysisKind
    status: str
    analysis_schema_version: int
    n_runs: int
    n_fail: int
    mode_codes: list[str]
    warnings: list[str]
    summary: dict[str, Any]
    duration_s: float
    artefact_sha256: dict[str, str] = field(default_factory=dict)


@dataclass
class AnalysisContext:
    """Mutable bag passed through the analyzer chain."""

    campaign_id: UUID
    kind: AnalysisKind
    settings: AnalysisSettings
    risk: RiskSettings
    clock: Clock
    uow: AnalysisUnitOfWork
    artifact_store: AnalysisArtifactStore
    space: ScenarioSpace | None = None
    campaign_seed: int = 0
    backend: str = "kinematic2d"
    runs: list[AnalysisRun] = field(default_factory=list)
    features: FeatureMatrix | None = None
    clustering: ClusteringResult | None = None
    modes: list[FailureModeSummary] = field(default_factory=list)
    mode_ids: dict[str, UUID] = field(default_factory=dict)
    importance: ImportanceReport | None = None
    rules: list[Rule] = field(default_factory=list)
    volumes: dict[str, Any] | None = None
    slices: list[Any] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    step_seconds: MutableMapping[str, float] = field(default_factory=dict)
    analysis_id: UUID | None = None
    optional_failed: bool = False
    gp_x: Any = None
    gp_y: Any = None
    gp_lengthscales: dict[str, float] | None = None


class Analyzer(Protocol):
    """One pluggable analysis step (entry-point group ``roboprobe.analyzers``)."""

    name: str

    def run(self, ctx: AnalysisContext) -> None:
        """Mutate ``ctx``; raise only for core-step failures."""
        ...
