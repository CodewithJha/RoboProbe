"""Evaluation metric definitions (MET-*) and statistics.

Layer: Domain (L2). See docs/16 §2 for the allowed import directions.

Implements: FR-EXP-001, FR-EXP-002, FR-EXP-003
"""

from roboprobe.metrics.campaign_metrics import (
    CampaignRun,
    FirstFailure,
    Replay,
    cost_per_mode,
    failure_discovery_rate,
    first_failure,
    is_comparison_run,
    reproducibility,
    robustness_delta,
    robustness_score,
)
from roboprobe.metrics.discovery_metrics import (
    bin_coverage_c2,
    boundary_accuracy,
    discovery_auc,
    discovery_curve,
    failure_region_coverage,
    pooled_cluster_hits,
    unique_gt_modes,
)
from roboprobe.metrics.statistics import (
    a12,
    bootstrap_ci,
    compare,
    effect_label,
    holm,
    mann_whitney_u,
)
from roboprobe.metrics.survival import kaplan_meier, logrank

__all__ = [
    "CampaignRun",
    "FirstFailure",
    "Replay",
    "a12",
    "bin_coverage_c2",
    "bootstrap_ci",
    "boundary_accuracy",
    "compare",
    "cost_per_mode",
    "discovery_auc",
    "discovery_curve",
    "effect_label",
    "failure_discovery_rate",
    "failure_region_coverage",
    "first_failure",
    "holm",
    "is_comparison_run",
    "kaplan_meier",
    "logrank",
    "mann_whitney_u",
    "pooled_cluster_hits",
    "reproducibility",
    "robustness_delta",
    "robustness_score",
    "unique_gt_modes",
]
