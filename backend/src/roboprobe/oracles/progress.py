"""O-PROG — stuck / no progress (docs/08 §3.3).

Implements: FR-ORC-001, FR-ORC-002, FR-ORC-005
"""

from __future__ import annotations

from typing import ClassVar, Literal

import numpy as np

from roboprobe.core.types import FailureClass, OracleResult, TaskSpec, Trace
from roboprobe.oracles._signals import at_goal, clip, nav_active
from roboprobe.oracles.base import Oracle

__all__ = ["ProgressOracle"]


class ProgressOracle(Oracle):
    """Displacement over a sliding window while navigation is active."""

    id: ClassVar[str] = "O-PROG"
    failure_class: ClassVar[FailureClass] = FailureClass.STUCK
    severity: ClassVar[Literal["failure", "warning"]] = "failure"

    def evaluate(self, trace: Trace, task: TaskSpec) -> OracleResult:
        """Clip of (min window displacement - delta_min) / delta_norm."""
        cfg = self.thresholds.prog
        if trace.n_samples == 0:
            return self._result(1.0, False, None, 0.0)
        t_past = trace.t - cfg.window_s
        x_past = np.interp(t_past, trace.t, trace.gt_x)
        y_past = np.interp(t_past, trace.t, trace.gt_y)
        delta = np.hypot(trace.gt_x - x_past, trace.gt_y - y_past)
        ready = trace.t >= trace.t[0] + cfg.window_s
        eligible = ready & nav_active(trace) & ~at_goal(trace, task)
        if not np.any(eligible):
            return self._result(1.0, False, None, float(np.min(delta)))
        min_delta = float(np.min(delta[eligible]))
        r = float(clip((min_delta - cfg.delta_min) / cfg.delta_norm))
        violated = min_delta < cfg.delta_min
        first = None
        if violated:
            bad = eligible & (delta < cfg.delta_min)
            first = float(trace.t[int(np.argmax(bad))])
        return self._result(r, violated, first, min_delta)

    def _result(
        self,
        r: float,
        violated: bool,
        first: float | None,
        min_delta: float,
    ) -> OracleResult:
        return OracleResult(
            oracle_id=self.id,
            failure_class=self.failure_class,
            severity=self.severity,
            robustness=r,
            violated=violated,
            first_violation_t=first,
            details={"min_delta_m": min_delta},
        )
