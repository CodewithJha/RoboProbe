"""Shared base class for settings sections.

Layer: Kernel (L1).
"""

from pydantic import BaseModel, ConfigDict


class SettingsSection(BaseModel):
    """Immutable settings section that rejects unknown keys (typos fail fast)."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)


PORT_MAX = 65535
"""Highest valid TCP/UDP port number."""
