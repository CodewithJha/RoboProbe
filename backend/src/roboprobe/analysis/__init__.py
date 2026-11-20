"""Failure analysis: features, clustering into failure modes, importance and rules.

Layer: Domain (L2). See docs/16 §2 for the allowed import directions.

Implements: FR-ANA-001, FR-ANA-002, FR-ANA-003, FR-ANA-004, FR-ANA-005, FR-ANA-006
"""

from roboprobe.analysis.base import AnalysisKind, AnalysisReport
from roboprobe.analysis.clustering import FailureClusterer
from roboprobe.analysis.features import FailureFeatureBuilder
from roboprobe.analysis.importance import ImportanceExplainer
from roboprobe.analysis.interaction import InteractionTester
from roboprobe.analysis.mode_matching import match_modes
from roboprobe.analysis.modes import ModeSummarizer, build_label
from roboprobe.analysis.pipeline import analyze_campaign
from roboprobe.analysis.rules import RuleExtractor, render_rule
from roboprobe.analysis.types import (
    AnalysisRun,
    ClusteringResult,
    ConfirmScenario,
    FailureModeSummary,
    FeatureMatrix,
    ImportanceReport,
    InteractionVerdict,
    ModeMatch,
    Rule,
)

__all__ = [
    "AnalysisKind",
    "AnalysisReport",
    "AnalysisRun",
    "ClusteringResult",
    "ConfirmScenario",
    "FailureClusterer",
    "FailureFeatureBuilder",
    "FailureModeSummary",
    "FeatureMatrix",
    "ImportanceExplainer",
    "ImportanceReport",
    "InteractionTester",
    "InteractionVerdict",
    "ModeMatch",
    "ModeSummarizer",
    "Rule",
    "RuleExtractor",
    "analyze_campaign",
    "build_label",
    "match_modes",
    "render_rule",
]
