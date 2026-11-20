"""Non-adaptive baseline strategies (docs/07 §3)."""

from roboprobe.selection.baselines.grid import GridStrategy
from roboprobe.selection.baselines.lhs import LHSStrategy
from roboprobe.selection.baselines.ofat import OFATStrategy
from roboprobe.selection.baselines.random import RandomStrategy
from roboprobe.selection.baselines.sobol import SobolStrategy

__all__ = [
    "GridStrategy",
    "LHSStrategy",
    "OFATStrategy",
    "RandomStrategy",
    "SobolStrategy",
]
