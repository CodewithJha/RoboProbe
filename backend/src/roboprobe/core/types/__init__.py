"""Shared core types — the normative contracts every module exchanges (docs/05 §1).

Import from this package (``from roboprobe.core.types import Scenario``), never from its private
sub-modules, so the internal split can change without touching callers.

Implements: FR-ORC-002, FR-RUN-004
"""

from pydantic import JsonValue

from roboprobe.core.types.enums import (
    CampaignStatus,
    FailureClass,
    NavStatus,
    ParamType,
    RunStatus,
    Verdict,
)
from roboprobe.core.types.models import (
    GoalTolerance,
    InjectedObstacle,
    Observation,
    ObstaclePlacement,
    OracleResult,
    ParamValue,
    Phase,
    Pose2D,
    Proposal,
    RunOutcome,
    Scenario,
    Severity,
    SutProfile,
    TaskField,
    TaskSpec,
    TimeLimitSpec,
)
from roboprobe.core.types.trace import FloatArray, Trace

__all__ = [
    "CampaignStatus",
    "FailureClass",
    "FloatArray",
    "GoalTolerance",
    "InjectedObstacle",
    "JsonValue",
    "NavStatus",
    "Observation",
    "ObstaclePlacement",
    "OracleResult",
    "ParamType",
    "ParamValue",
    "Phase",
    "Pose2D",
    "Proposal",
    "RunOutcome",
    "RunStatus",
    "Scenario",
    "Severity",
    "SutProfile",
    "TaskField",
    "TaskSpec",
    "TimeLimitSpec",
    "Trace",
    "Verdict",
]
