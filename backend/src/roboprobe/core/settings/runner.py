"""Orchestrator (campaign runner) settings (docs/27 §4.4).

Layer: Kernel (L1).
"""

from typing import Self

from pydantic import Field, model_validator

from roboprobe.core.settings._base import SettingsSection

__all__ = [
    "AlertSettings",
    "AutoPauseSettings",
    "RetrySettings",
    "RunnerAnalysisSettings",
    "RunnerSettings",
]


class AutoPauseSettings(SettingsSection):
    """Automatic campaign pause when too many runs are INVALID."""

    invalid_ratio: float = Field(
        default=0.2, gt=0, le=1, description="INVALID share that pauses a campaign [0-1]."
    )
    min_runs: int = Field(
        default=20, ge=0, description="Finished runs before `invalid_ratio` is evaluated."
    )
    max_consecutive_invalid: int = Field(
        default=10, gt=0, description="Consecutive INVALID runs that pause a campaign."
    )


class AlertSettings(SettingsSection):
    """In-app alert thresholds (docs/21 §5.5)."""

    no_workers_after_s: float = Field(
        default=60.0,
        gt=0,
        description="Emit NO_WORKERS when a RUNNING campaign has no worker this long [s].",
    )
    gp_fallback_repeat: int = Field(
        default=3,
        ge=1,
        description="Emit GP_FALLBACK_REPEATED after this many consecutive selector fallbacks.",
    )


class RunnerAnalysisSettings(SettingsSection):
    """Incremental analysis triggered by the campaign loop."""

    incremental_every_n: int = Field(
        default=25, gt=0, description="Re-run incremental failure analysis every N finished runs."
    )
    max_workers: int = Field(
        default=1,
        gt=0,
        description="Concurrent analysis jobs per orchestrator process (ThreadPoolExecutor).",
    )


class RetrySettings(SettingsSection):
    """Bounded exponential backoff for transient infrastructure errors (docs/34 §5)."""

    max_attempts: int = Field(default=3, ge=1, description="Attempts including the first.")
    base_delay_s: float = Field(default=0.5, gt=0, description="First backoff delay [s].")
    max_delay_s: float = Field(default=10.0, gt=0, description="Backoff delay cap [s].")

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.base_delay_s > self.max_delay_s:
            msg = "runner.retry.base_delay_s must not exceed runner.retry.max_delay_s"
            raise ValueError(msg)
        return self


class RunnerSettings(SettingsSection):
    """Campaign loop, reaper and budget limits."""

    tick_interval_s: float = Field(default=1.0, gt=0, description="Campaign loop tick [s].")
    inflight_factor: float = Field(
        default=1.5, gt=0, description="Target in-flight runs = workers x factor."
    )
    reaper_interval_s: float = Field(default=10.0, gt=0, description="Reaper sweep interval [s].")
    heartbeat_timeout_s: float = Field(
        default=30.0, gt=0, description="Heartbeat age after which a run is reaped [s]."
    )
    max_attempts: int = Field(default=3, ge=1, description="Run attempts (1 + retries).")
    max_budget: int = Field(default=20000, gt=0, description="Maximum runs per campaign.")
    max_batch_size: int = Field(default=32, gt=0, description="Maximum proposals per batch.")
    auto_pause: AutoPauseSettings = Field(default_factory=AutoPauseSettings)
    alerts: AlertSettings = Field(default_factory=AlertSettings)
    analysis: RunnerAnalysisSettings = Field(default_factory=RunnerAnalysisSettings)
    count_invalid_in_budget: bool = Field(
        default=False, description="Whether INVALID runs consume campaign budget."
    )
    retry: RetrySettings = Field(default_factory=RetrySettings)
    max_concurrent_campaigns: int = Field(
        default=4, gt=0, description="Campaigns driven concurrently per orchestrator."
    )
    confirm_priority: int = Field(
        default=10,
        ge=0,
        description="Queue priority for confirmatory interaction runs (lower runs sooner).",
    )
