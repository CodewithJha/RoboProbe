"""Enumerations shared across modules (docs/05 §1); string values are stable identifiers.

Implements: FR-ORC-002, FR-RUN-004
"""

from __future__ import annotations

from enum import IntEnum, StrEnum

__all__ = ["CampaignStatus", "FailureClass", "NavStatus", "ParamType", "RunStatus", "Verdict"]

# --------------------------------------------------------------------------- enums


class ParamType(StrEnum):
    """Type of a scenario parameter (docs/06 §2)."""

    FLOAT = "float"
    INT = "int"
    CATEGORICAL = "categorical"


class Verdict(StrEnum):
    """Outcome of judging one run (docs/08 §3)."""

    PASS = "PASS"  # noqa: S105 - verdict identifier, not a credential
    FAIL = "FAIL"
    INVALID = "INVALID"


class FailureClass(StrEnum):
    """Failure taxonomy identifiers (docs/08 §2); values are the documented IDs verbatim."""

    COL = "F-COL"
    NEAR = "F-NEAR"
    TIMEOUT = "F-TIMEOUT"
    STUCK = "F-STUCK"
    LOC = "F-LOC"
    PLAN = "F-PLAN"
    INST = "F-INST"
    OSC = "F-OSC"
    INFRA = "F-INFRA"


class RunStatus(StrEnum):
    """Lifecycle state of a run (docs/11 ``runs.status``)."""

    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    EVALUATING = "EVALUATING"
    DONE = "DONE"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


class CampaignStatus(StrEnum):
    """Lifecycle state of a campaign (docs/11 ``campaigns.status``)."""

    CREATED = "CREATED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ANALYZING = "ANALYZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class NavStatus(IntEnum):
    """Navigation action status encoded in :attr:`Trace.nav_status` (docs/05 §1)."""

    IDLE = 0
    ACTIVE = 1
    SUCCEEDED = 2
    ABORTED = 3
    CANCELED = 4
