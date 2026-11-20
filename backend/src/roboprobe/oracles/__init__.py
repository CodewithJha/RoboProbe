"""Robustness-valued failure oracles and verdict aggregation.

Layer: Domain (L2). See docs/16 §2 for the allowed import directions.

Implements: FR-ORC-001, FR-ORC-002, FR-ORC-003, FR-ORC-004, FR-ORC-005, FR-ORC-006
"""

from roboprobe.oracles.base import Oracle
from roboprobe.oracles.clearance import ClearanceOracle
from roboprobe.oracles.goal import GoalOracle
from roboprobe.oracles.infra import InfraCheck
from roboprobe.oracles.localization import LocalizationOracle
from roboprobe.oracles.metrics import compute_run_metrics
from roboprobe.oracles.nav import NavStatusOracle
from roboprobe.oracles.oscillation import OscillationOracle
from roboprobe.oracles.progress import ProgressOracle
from roboprobe.oracles.registry import OracleRegistry, create_all
from roboprobe.oracles.stability import StabilityOracle
from roboprobe.oracles.verdict import VerdictEngine

__version__ = "oracles-1"
"""``oracle_set_version`` stored per campaign (docs/33 §6). Bump on formula/default changes."""

__all__ = [
    "ClearanceOracle",
    "GoalOracle",
    "InfraCheck",
    "LocalizationOracle",
    "NavStatusOracle",
    "Oracle",
    "OracleRegistry",
    "OscillationOracle",
    "ProgressOracle",
    "StabilityOracle",
    "VerdictEngine",
    "__version__",
    "compute_run_metrics",
    "create_all",
]
