"""Value objects for failure analysis (docs/09, docs/05 §7).

Implements: FR-ANA-001, FR-ANA-002, FR-ANA-003, FR-ANA-004, FR-ANA-005
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import numpy as np
import numpy.typing as npt
from pydantic import Field

from roboprobe.core.settings.oracles import OracleThresholds
from roboprobe.core.types import FailureClass, ParamValue, Phase, Scenario, Verdict
from roboprobe.core.types.models import _Frozen

__all__ = [
    "AnalysisRun",
    "ClusteringResult",
    "Condition",
    "ConfirmScenario",
    "FailureModeSummary",
    "FeatureDiagnostics",
    "FeatureMatrix",
    "ImportanceReport",
    "InteractionVerdict",
    "ModeMatch",
    "ParamRange",
    "Rule",
    "StoredMode",
]


class AnalysisRun(_Frozen):
    """One finished run as seen by analysis (store :class:`RunRecord` maps here later)."""

    id: UUID
    verdict: Verdict
    phase: Phase
    primary_failure: FailureClass | None
    values: dict[str, ParamValue]
    metrics: dict[str, float] = Field(default_factory=dict)
    oracle_thresholds: OracleThresholds = Field(default_factory=OracleThresholds)
    subset: frozenset[str] | None = None


@dataclass(frozen=True, slots=True)
class FeatureDiagnostics:
    """Counts from :class:`FailureFeatureBuilder.build`."""

    n_input: int
    n_fail: int
    n_excluded_invalid: int
    missing_traj: bool


@dataclass(frozen=True, slots=True)
class FeatureMatrix:
    """Weighted feature rows of failing runs (docs/09 §3.1)."""

    X: npt.NDArray[np.float64]
    run_ids: tuple[UUID, ...]
    columns: tuple[str, ...]
    space_version: int
    classes: tuple[FailureClass | None, ...]
    diagnostics: FeatureDiagnostics


@dataclass(frozen=True, slots=True)
class ClusteringResult:
    """HDBSCAN (or class-fallback) labels aligned with :attr:`run_ids`."""

    labels: npt.NDArray[np.intp]
    probabilities: npt.NDArray[np.float64]
    outlier_scores: npt.NDArray[np.float64]
    method: Literal["hdbscan", "class_fallback"]
    min_cluster_size: int
    provisional: bool
    run_ids: tuple[UUID, ...]
    X: npt.NDArray[np.float64]


class ParamRange(_Frozen):
    """Physical [q05, q95] of a mode on one parameter, plus unit-space coverage."""

    unit: str
    q05: float
    q95: float
    space_coverage: float


class FailureModeSummary(_Frozen):
    """Human-readable cluster summary (docs/09 §3.3)."""

    code: str
    size: int
    primary_class: FailureClass
    class_mix: Mapping[FailureClass, float]
    ranges: Mapping[str, ParamRange]
    characteristic: frozenset[str]
    medoid_run_id: UUID
    minimal_run_id: UUID
    minimal_values: dict[str, ParamValue]
    member_run_ids: tuple[UUID, ...]
    label: str
    provisional: bool


class StoredMode(_Frozen):
    """Previously persisted mode, used only for identity matching."""

    id: UUID
    code: str
    member_run_ids: frozenset[UUID]
    label: str
    label_is_user: bool
    status: str = "active"


class ModeMatch(_Frozen):
    """Hungarian assignment of new clusters onto stored modes."""

    assignments: dict[int, UUID]
    new_codes: dict[int, str]
    preserved_labels: dict[int, str]
    stale_ids: tuple[UUID, ...]


class ImportanceReport(_Frozen):
    """JSON-serialisable SHAP importance (docs/09 §4)."""

    names: tuple[str, ...]
    mean_abs_shap: tuple[float, ...]
    interactions: tuple[tuple[float, ...], ...]
    auc_mean: float | None
    auc_std: float | None
    balanced_acc_mean: float | None
    balanced_acc_std: float | None
    low_confidence: bool
    model_kind: str
    gp_normalized: tuple[float, ...] | None
    disagreement: tuple[str, ...]
    per_mode: dict[str, tuple[float, ...]]


class Condition(_Frozen):
    """One predicate of an extracted rule, in unit and physical units."""

    param: str
    op: Literal["<", "≥"]
    threshold_unit: float
    threshold_physical: float
    unit: str


class Rule(_Frozen):
    """A FAIL leaf of the shallow tree, rendered in physical units."""

    conditions: tuple[Condition, ...]
    precision: float
    support: int
    primary_class: FailureClass | None
    mode_code: str | None
    text: str


class ConfirmScenario(_Frozen):
    """A confirmatory scenario tagged with the characteristic subset it sets."""

    scenario: Scenario
    subset: frozenset[str]
    tags: tuple[str, ...]
    seed: int
    repeat: int


class InteractionVerdict(_Frozen):
    """Result of the interaction-failure test (docs/09 §6)."""

    status: Literal["CONFIRMED", "NOT_INTERACTION", "INCONCLUSIVE"]
    order: int | None
    params: tuple[str, ...]
    ratios: Mapping[str, float]
    evidence_run_ids: tuple[UUID, ...]
