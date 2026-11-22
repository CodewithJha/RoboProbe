"""Evaluation experiment settings (docs/27 §4.9, docs/19).

Layer: Kernel (L1).
"""

from pydantic import Field

from roboprobe.core.settings._base import SettingsSection

__all__ = ["ExperimentSettings", "ReferenceSetSettings"]


class ReferenceSetSettings(SettingsSection):
    """Dense reference sample used as ground truth for evaluation metrics."""

    n: int = Field(default=20000, gt=0, description="Reference scenarios.")
    seed: int = Field(default=20261119, ge=0, description="Seed of the reference sample.")
    space_id: str = Field(default="warehouse_v1", min_length=1, description="Scenario space id.")
    artifact_relpath: str = Field(
        default="reference/warehouse_v1_k2d.parquet",
        min_length=1,
        description="Relative path under artifact root.",
    )


class ExperimentSettings(SettingsSection):
    """Experiment runner and statistics settings."""

    default_seeds: int = Field(default=30, gt=0, description="Seeds per strategy and design.")
    max_concurrent_campaigns: int = Field(
        default=2, gt=0, description="Campaigns an experiment runs concurrently."
    )
    bootstrap_resamples: int = Field(
        default=10000, gt=0, description="Bootstrap resamples for confidence intervals."
    )
    alpha: float = Field(default=0.05, gt=0, lt=1, description="Significance level.")
    reference_set: ReferenceSetSettings = Field(default_factory=ReferenceSetSettings)
    mode_match_radius: float = Field(
        default=0.05, gt=0, description="Unit-cube radius matching a found mode to a true one."
    )
    coverage_bins: int = Field(default=5, gt=0, description="Bins per axis for coverage metrics.")
