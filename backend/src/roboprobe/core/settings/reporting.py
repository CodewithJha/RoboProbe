"""Static HTML report and figure settings (docs/27, docs/05 §12).

Layer: Kernel (L1).

Implements: T-078a, T-078b, T-079
"""

from typing import Literal

from pydantic import Field

from roboprobe.core.settings._base import SettingsSection

__all__ = ["FigureSettings", "ReportingSettings"]


class FigureSettings(SettingsSection):
    """Matplotlib figure dimensions for embedded SVG reports."""

    width_in: float = Field(default=6.0, gt=0, description="Figure width in inches.")
    height_in: float = Field(default=4.0, gt=0, description="Figure height in inches.")
    dpi: int = Field(default=100, gt=0, description="Rasterisation DPI (SVG metadata only).")


class ReportingSettings(SettingsSection):
    """Offline report rendering defaults."""

    theme: Literal["light", "dark"] = Field(
        default="light", description="Colour theme token set (Field Notebook)."
    )
    figures: FigureSettings = Field(default_factory=FigureSettings)
