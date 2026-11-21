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
    constraint_max_literal_exponent: int = Field(
        default=8,
        ge=1,
        description="Largest absolute integer exponent allowed in a constraint (TM-03).",
    )
    yaml_max_aliases: int = Field(
        default=32,
        ge=0,
        description="Maximum YAML alias expansions in one uploaded document (TM-02).",
    )
