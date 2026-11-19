"""Scenario generation settings (docs/27 §4.7, docs/06).

Layer: Kernel (L1).
"""

from pydantic import Field

from roboprobe.core.settings._base import SettingsSection

__all__ = ["ScenarioSettings"]


class ScenarioSettings(SettingsSection):
    """Scenario sampling settings shared by every strategy."""

    constraint_max_attempts: int = Field(
        default=1000,
        ge=1,
        description="Sampler draws before rejection sampling of constrained spaces gives up.",
    )
