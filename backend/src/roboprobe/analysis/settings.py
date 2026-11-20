"""Analysis tunables that extend :class:`AnalysisSettings` without changing kernel models.

Implements: FR-ANA-001, FR-ANA-003, FR-ANA-004
"""

from __future__ import annotations

from pydantic import Field

from roboprobe.core.settings._base import SettingsSection
from roboprobe.core.settings.analysis import AnalysisSettings, HdbscanSettings, RulesSettings

__all__ = [
    "ClustererSettings",
    "ImportanceSettings",
    "LabelLexicon",
    "RuleExtractorSettings",
]


class ClustererSettings(HdbscanSettings):
    """HDBSCAN settings plus small-n fallback knobs (docs/09 §3.2)."""

    min_samples: int | None = Field(
        default=None, ge=1, description="HDBSCAN min_samples; None copies min_cluster_size."
    )
    min_failures_for_clustering: int = Field(
        default=6, ge=1, description="Below this, group by failure class instead of HDBSCAN."
    )


class ImportanceSettings(SettingsSection):
    """HistGB + SHAP explainer settings (docs/09 §4)."""

    max_depth: int = Field(default=4, ge=1)
    learning_rate: float = Field(default=0.1, gt=0, le=1)
    max_iter: int = Field(default=200, ge=1)
    cv_folds: int = Field(default=5, ge=2)
    min_failures_confident: int = Field(default=10, ge=1)
    min_cv_auc: float = Field(default=0.7, gt=0, le=1)
    shap_max_samples: int = Field(default=1000, ge=1)
    rank_disagreement: int = Field(
        default=2, ge=1, description="Rank gap that flags SHAP vs lengthscale disagreement."
    )

    @classmethod
    def from_analysis(cls, settings: AnalysisSettings) -> ImportanceSettings:
        """Copy GBM/CV fields from campaign :class:`AnalysisSettings`."""
        return cls(
            max_depth=settings.gbm.max_depth,
            learning_rate=settings.gbm.learning_rate,
            max_iter=settings.gbm.max_iter,
            cv_folds=settings.cv_folds,
            min_failures_confident=settings.min_failures_confident,
        )


class RuleExtractorSettings(RulesSettings):
    """Decision-tree rule extraction plus leaf-size knobs (docs/09 §4.3)."""

    min_leaf_fraction: float = Field(default=0.02, gt=0, le=1)
    min_leaf_size_floor: int = Field(default=3, ge=1)
    max_conditions: int = Field(default=4, ge=1)


class LabelLexicon(SettingsSection):
    """Words and short names used in auto-labels (docs/09 §3.3)."""

    high: str = Field(default="high")
    low: str = Field(default="low")
    joiner: str = Field(default=" · ")
    aliases: dict[str, str] = Field(
        default_factory=lambda: {
            "max_speed": "speed",
            "illuminance": "light",
            "lidar_noise_std": "noise",
        }
    )
    top_n: int = Field(default=3, ge=1)
    medoid_sample_cap: int = Field(default=500, ge=1)
    quantile_lo: float = Field(default=0.05, ge=0, le=1)
    quantile_hi: float = Field(default=0.95, ge=0, le=1)
    display_sigfigs: int = Field(default=2, ge=1)
    interaction_cap: int = Field(default=4, ge=1)
