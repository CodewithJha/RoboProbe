"""O-STAB — instability / tip-over (docs/08 §3.6).

Implements: FR-ORC-001, FR-ORC-002, FR-ORC-005
"""

from __future__ import annotations

from typing import ClassVar, Literal

import numpy as np

from roboprobe.core.types import FailureClass, OracleResult, TaskSpec, Trace
from roboprobe.oracles._signals import clip
from roboprobe.oracles.base import Oracle

__all__ = ["StabilityOracle"]


class StabilityOracle(Oracle):
    """Roll/pitch and measured yaw-rate limits."""

    id: ClassVar[str] = "O-STAB"
    failure_class: ClassVar[FailureClass] = FailureClass.INST
    severity: ClassVar[Literal["failure", "warning"]] = "failure"

    def evaluate(self, trace: Trace, task: TaskSpec) -> OracleResult:
        """Min of tilt and yaw-rate margins, clipped to [-1, 1]."""
        del task
        cfg = self.thresholds.stab
        if trace.n_samples == 0:
            return self._result(1.0, False, None, 0.0, 0.0)
        tilt = np.maximum(np.abs(trace.roll), np.abs(trace.pitch))
        omega = np.abs(trace.meas_w)
        max_tilt = float(np.max(tilt))
        max_w = float(np.max(omega))
        r = float(clip(min(1.0 - max_tilt / cfg.theta_max, 1.0 - max_w / cfg.omega_max)))
        violated = max_tilt > cfg.theta_max or max_w > cfg.omega_max
        first = None
        if violated:
            bad = (tilt > cfg.theta_max) | (omega > cfg.omega_max)
            first = float(trace.t[int(np.argmax(bad))])
        return self._result(r, violated, first, max_tilt, max_w)

    def _result(
        self,
        r: float,
        violated: bool,
        first: float | None,
        max_tilt: float,
        max_w: float,
    ) -> OracleResult:
        return OracleResult(
            oracle_id=self.id,
            failure_class=self.failure_class,
            severity=self.severity,
            robustness=r,
            violated=violated,
            first_violation_t=first,
            details={"max_tilt_rad": max_tilt, "max_omega_rad_s": max_w},
        )
