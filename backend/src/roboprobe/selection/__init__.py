"""Test-selection strategies: baselines, surrogate models, acquisition and S-PROBE.

Layer: Domain (L2). See docs/16 §2 for the allowed import directions.
"""

from roboprobe.selection.base import (
    HISTORY_LINF_TOL,
    PLUGIN_API_VERSION,
    Strategy,
    StrategyContext,
    StrategyParams,
)
from roboprobe.selection.registry import available, create, get, register

__all__ = [
    "HISTORY_LINF_TOL",
    "PLUGIN_API_VERSION",
    "Strategy",
    "StrategyContext",
    "StrategyParams",
    "available",
    "create",
    "get",
    "register",
]
