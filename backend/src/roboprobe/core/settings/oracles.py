"""Default oracle thresholds (docs/27 §4.6, docs/08 §4).

Layer: Kernel (L1). Campaigns may override these; resolved values are snapshotted per campaign.
"""

from pydantic import Field

from roboprobe.core.settings._base import SettingsSection

__all__ = [
    "ClearanceThresholds",
    "GoalThresholds",
    "InfraThresholds",
    "LocalizationThresholds",
    "NavThresholds",
    "OracleThresholds",
    "OscillationThresholds",
    "ProgressThresholds",
    "StabilityThresholds",
]


class ClearanceThresholds(SettingsSection):
    """O-CLEAR: collision / near-miss oracle."""

    d_norm: float = Field(default=0.5, gt=0, description="Clearance normaliser [m].")
    d_safe: float = Field(default=0.10, ge=0, description="Near-miss (F-NEAR) distance [m].")
    r_contact_base: float = Field(
        default=0.1, ge=0, le=1, description="Robustness magnitude of a zero-speed contact."
    )
    v_ref: float = Field(default=0.5, gt=0, description="Impact speed normaliser [m/s].")


class GoalThresholds(SettingsSection):
    """O-GOAL: goal-reached oracle."""

    r_min: float = Field(
        default=0.01, gt=0, le=1, description="Minimum robustness magnitude when not reached."
    )


class ProgressThresholds(SettingsSection):
    """O-PROG: lack-of-progress (stuck) oracle."""

    window_s: float = Field(default=10.0, gt=0, description="Progress window [s].")
    delta_min: float = Field(default=0.05, ge=0, description="Minimum progress per window [m].")
    delta_norm: float = Field(default=0.5, gt=0, description="Progress normaliser [m].")


class LocalizationThresholds(SettingsSection):
    """O-LOC: localisation error oracle."""

    e_max: float = Field(default=0.5, gt=0, description="Maximum tolerated pose error [m].")
    hold_s: float = Field(default=2.0, ge=0, description="Time the error must persist [s].")


class NavThresholds(SettingsSection):
    """O-NAV: navigation-stack abort oracle."""

    r_abort: float = Field(
        default=-0.5, ge=-1, lt=0, description="Robustness assigned to a navigation abort."
    )


class StabilityThresholds(SettingsSection):
    """O-STAB: tip-over / instability oracle."""

    theta_max: float = Field(default=0.35, gt=0, description="Maximum roll/pitch [rad].")
    omega_max: float = Field(default=3.0, gt=0, description="Maximum angular rate [rad/s].")


class OscillationThresholds(SettingsSection):
    """O-OSC: oscillation oracle."""

    window_s: float = Field(default=5.0, gt=0, description="Sliding window [s].")
    omega_min: float = Field(
        default=0.3, ge=0, description="Yaw-rate magnitude counted as a swing [rad/s]."
    )
    n_max: int = Field(default=6, gt=0, description="Sign changes per window before violation.")


class InfraThresholds(SettingsSection):
    """O-INFRA: run validity checks (INVALID verdicts)."""

    max_gap_s: float = Field(default=1.0, gt=0, description="Largest allowed sampling gap [s].")
    min_rtf: float = Field(default=0.2, gt=0, description="Minimum mean real-time factor.")
    startup_timeout_s: float = Field(
        default=60.0, gt=0, description="Time allowed for the stack to become ACTIVE [s]."
    )
    spawn_tolerance_m: float = Field(
        default=0.2, gt=0, description="Allowed deviation of the spawn pose [m]."
    )


class OracleThresholds(SettingsSection):
    """Default thresholds of every oracle."""

    clear: ClearanceThresholds = Field(default_factory=ClearanceThresholds)
    goal: GoalThresholds = Field(default_factory=GoalThresholds)
    prog: ProgressThresholds = Field(default_factory=ProgressThresholds)
    loc: LocalizationThresholds = Field(default_factory=LocalizationThresholds)
    nav: NavThresholds = Field(default_factory=NavThresholds)
    stab: StabilityThresholds = Field(default_factory=StabilityThresholds)
    osc: OscillationThresholds = Field(default_factory=OscillationThresholds)
    infra: InfraThresholds = Field(default_factory=InfraThresholds)
