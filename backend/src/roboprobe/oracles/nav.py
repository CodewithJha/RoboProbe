"""O-NAV — Nav2 abort (docs/08 §3.5).

Implements: FR-ORC-001, FR-ORC-002, FR-ORC-005
"""

from __future__ import annotations

from typing import ClassVar, Literal

import numpy as np

from roboprobe.core.types import FailureClass, NavStatus, OracleResult, TaskSpec, Trace
from roboprobe.oracles._signals import t_goal_s
from roboprobe.oracles.base import Oracle

__all__ = ["NavStatusOracle"]


class NavStatusOracle(Oracle):
    """Discrete abort: ``r = r_abort`` if final status is ABORTED before the goal."""

    id: ClassVar[str] = "O-NAV"
    failure_class: ClassVar[FailureClass] = FailureClass.PLAN
    severity: ClassVar[Literal["failure", "warning"]] = "failure"

    def evaluate(self, trace: Trace, task: TaskSpec) -> OracleResult:
        """Violate iff the last sample is ABORTED and the goal was never reached."""
        r_abort = self.thresholds.nav.r_abort
        reached = t_goal_s(trace, task) is not None
        aborted = (
            trace.n_samples > 0
            and int(trace.nav_status[-1]) == int(NavStatus.ABORTED)
            and not reached
        )
        first = None
        if aborted:
            hits = trace.nav_status == np.int8(NavStatus.ABORTED)
            first = float(trace.t[int(np.argmax(hits))])
        return OracleResult(
            oracle_id=self.id,
            failure_class=self.failure_class,
            severity=self.severity,
            robustness=r_abort if aborted else 1.0,
            violated=aborted,
            first_violation_t=first,
            details={"final_nav_status": float(trace.nav_status[-1]) if trace.n_samples else -1.0},
        )
