"""Failure-analysis and risk-mapping settings (docs/27 §4.8, docs/09).

Layer: Kernel (L1).
"""

from typing import Self

from pydantic import ConfigDict, Field, model_validator

from roboprobe.core.settings._base import SettingsSection

__all__ = [
    "AnalysisSettings",
    "FeatureWeights",
    "GbmSettings",
    "HdbscanSettings",
    "InteractionSettings",
    "RiskSettings",
    "RiskThresholds",
    "RulesSettings",
]

_MIN_CV_FOLDS = 2
_MIN_SLICE_RESOLUTION = 2


class FeatureWeights(SettingsSection):
    """Weights of the feature blocks used for failure clustering."""

    param: float = Field(default=1.0, ge=0, description="Scenario-parameter block weight.")
    class_: float = Field(
        default=0.75, ge=0, alias="class", description="Failure-class block weight."
    )
    traj: float = Field(default=0.5, ge=0, description="Trajectory-feature block weight.")

    model_config = ConfigDict(validate_by_name=True, validate_by_alias=True)


class HdbscanSettings(SettingsSection):
    """HDBSCAN clustering of failures."""

    min_cluster_fraction: float = Field(
        default=0.03, gt=0, le=1, description="Minimum cluster size as a share of failures."
    )
    min_cluster_size_floor: int = Field(
        default=3, ge=1, description="Absolute minimum cluster size."
    )


class GbmSettings(SettingsSection):
    """Gradient-boosting classifier used for parameter importance."""

    max_depth: int = Field(default=4, ge=1, description="Maximum tree depth.")
    learning_rate: float = Field(default=0.1, gt=0, le=1, description="Learning rate.")
    max_iter: int = Field(default=200, ge=1, description="Boosting iterations.")


class RulesSettings(SettingsSection):
    """Decision-tree rule extraction for failure modes."""

    max_depth: int = Field(default=4, ge=1, description="Maximum rule depth.")
    min_precision: float = Field(
        default=0.6, gt=0, le=1, description="Minimum precision of a reported rule."
    )


class InteractionSettings(SettingsSection):
    """Interaction (combined-factor) confirmation experiments."""

    repeats: int = Field(default=3, ge=1, description="Confirmation repeats per candidate.")
    success_ratio: float = Field(
        default=0.67, gt=0, le=1, description="Share of repeats that must reproduce the failure."
    )


class AnalysisSettings(SettingsSection):
    """Failure-analysis pipeline settings."""

    feature_weights: FeatureWeights = Field(default_factory=FeatureWeights)
    hdbscan: HdbscanSettings = Field(default_factory=HdbscanSettings)
    mode_match_jaccard: float = Field(
        default=0.5, ge=0, le=1, description="Jaccard overlap that matches modes across runs."
    )
    characteristic_coverage: float = Field(
        default=0.5, ge=0, le=1, description="Coverage for a parameter range to be characteristic."
    )
    gbm: GbmSettings = Field(default_factory=GbmSettings)
    cv_folds: int = Field(default=5, ge=_MIN_CV_FOLDS, description="Cross-validation folds.")
    min_failures_confident: int = Field(
        default=10, ge=1, description="Failures needed before results are flagged confident."
    )
    rules: RulesSettings = Field(default_factory=RulesSettings)
    interaction: InteractionSettings = Field(default_factory=InteractionSettings)


class RiskThresholds(SettingsSection):
    """Failure-probability cut-offs of the safe / uncertain / failure regions."""

    safe: float = Field(default=0.05, gt=0, lt=1, description="Upper bound of the safe region.")
    failure: float = Field(
        default=0.95, gt=0, lt=1, description="Lower bound of the failure-prone region."
    )

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        if self.safe >= self.failure:
            msg = "risk.thresholds.safe must be below risk.thresholds.failure"
            raise ValueError(msg)
        return self


class RiskSettings(SettingsSection):
    """Risk-map settings."""

    thresholds: RiskThresholds = Field(default_factory=RiskThresholds)
    slice_resolution: int = Field(
        default=50, ge=_MIN_SLICE_RESOLUTION, description="Grid points per axis of a 2-D slice."
    )
    volume_samples: int = Field(
        default=8192,
        ge=1,
        description="Sobol QMC sample count for region volume estimates (power of two).",
    )

    @model_validator(mode="after")
    def _volume_power_of_two(self) -> Self:
        samples = self.volume_samples
        if samples & (samples - 1) != 0:
            msg = "risk.volume_samples must be a power of two"
            raise ValueError(msg)
        return self
