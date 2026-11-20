"""Field Notebook design tokens for static reports (docs/13 §1.1).

Implements: T-078a, FR-DSH-007
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Literal

from roboprobe.core.settings.reporting import ReportingSettings

__all__ = ["ReportTheme", "load_theme", "tokens_path"]


@dataclass(frozen=True, slots=True)
class ReportTheme:
    """Resolved colours and fonts for Matplotlib and inline CSS."""

    mode: Literal["light", "dark"]
    paper: str
    paper_raised: str
    ink: str
    ink_muted: str
    margin_line: str
    accent: str
    risk_safe: str
    risk_uncertain: str
    risk_failure: str
    invalid: str
    font_sans: str
    font_mono: str


def tokens_path() -> Path:
    """Package path to the synced token JSON (doc 13)."""
    ref = resources.files("roboprobe.reporting.assets") / "tokens.json"
    with resources.as_file(ref) as path:
        return path


@lru_cache(maxsize=2)
def load_theme(mode: Literal["light", "dark"] | None = None) -> ReportTheme:
    """Load token values from ``reporting/assets/tokens.json``."""
    resolved = mode or ReportingSettings().theme
    raw = json.loads(tokens_path().read_text(encoding="utf-8"))
    palette = raw[resolved]
    fonts = raw["font"]
    return ReportTheme(
        mode=resolved,
        paper=str(palette["--paper"]),
        paper_raised=str(palette["--paper-raised"]),
        ink=str(palette["--ink"]),
        ink_muted=str(palette["--ink-muted"]),
        margin_line=str(palette["--margin-line"]),
        accent=str(palette["--accent"]),
        risk_safe=str(palette["--risk-safe"]),
        risk_uncertain=str(palette["--risk-uncertain"]),
        risk_failure=str(palette["--risk-failure"]),
        invalid=str(palette["--invalid"]),
        font_sans=str(fonts["--font-sans"]),
        font_mono=str(fonts["--font-mono"]),
    )


def verdict_colour(theme: ReportTheme, verdict: str) -> str:
    """Map a verdict label to a theme colour."""
    if verdict == "PASS":
        return theme.risk_safe
    if verdict == "FAIL":
        return theme.risk_failure
    return theme.invalid
