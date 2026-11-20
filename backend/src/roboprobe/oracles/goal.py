"""O-GOAL — timeout / goal reached (docs/08 §3.2).

Implements: FR-ORC-001, FR-ORC-002, FR-ORC-005
"""

from __future__ import annotations

from typing import ClassVar, Literal

import numpy as np

from roboprobe.core.types import FailureClass, OracleResult, TaskSpec, Trace
from roboprobe.oracles._signals import (
    P1_NOMINAL_MAX_SPEED_MPS,
    clip,
    nominal_polyline,
    remaining_path_length_m,
    t_goal_s,
)
from roboprobe.oracles.base import Oracle
from roboprobe.scenario.task import polyline_length_m, time_limit_s

__all__ = ["GoalOracle"]


class GoalOracle(Oracle):
    """Mission timeout: reached ⇒ leftover time; missed ⇒ remaining path fraction."""

    id: ClassVar[str] = "O-GOAL"
    failure_class: ClassVar[FailureClass] = FailureClass.TIMEOUT
    severity: ClassVar[Literal["failure", "warning"]] = "failure"

    def evaluate(self, trace: Trace, task: TaskSpec) -> OracleResult:
        """Leftover time if reached; remaining-path fraction if not."""
        poly = nominal_polyline(task)
        length = polyline_length_m(poly)
        speed = float(np.max(np.abs(trace.cmd_v))) if trace.n_samples else 0.0
        v_max = speed if speed > 0.0 else P1_NOMINAL_MAX_SPEED_MPS
        t_max = time_limit_s(task, v_max, length)
        t_goal = t_goal_s(trace, task)
        if t_goal is not None and t_goal <= t_max:
            r = float(clip((t_max - t_goal) / t_max))
            return OracleResult(
                oracle_id=self.id,
                failure_class=self.failure_class,
                severity=self.severity,
                robustness=r,
                violated=False,
                first_violation_t=None,
                details={"t_goal_s": t_goal, "t_max_s": t_max, "path_length_m": length},
            )
        last_x = float(trace.gt_x[-1]) if trace.n_samples else task.start.x
        last_y = float(trace.gt_y[-1]) if trace.n_samples else task.start.y
        d_rem = float(remaining_path_length_m(last_x, last_y, poly)[0])
        denom = length if length > 0.0 else 1.0
        r = -float(clip(max(self.thresholds.goal.r_min, d_rem / denom)))
        t_fail = t_max if t_goal is None or t_goal > t_max else t_goal
        return OracleResult(
            oracle_id=self.id,
            failure_class=self.failure_class,
            severity=self.severity,
            robustness=r,
            violated=True,
            first_violation_t=t_fail,
            details={
                "t_goal_s": t_goal if t_goal is not None else -1.0,
                "t_max_s": t_max,
                "d_remaining_m": d_rem,
                "path_length_m": length,
            },
        )
