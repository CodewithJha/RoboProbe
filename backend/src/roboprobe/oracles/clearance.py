"""O-CLEAR — collision and near-miss (docs/08 §3.1).

Implements: FR-ORC-001, FR-ORC-002, FR-ORC-005
"""

from __future__ import annotations

from typing import ClassVar, Literal

import numpy as np

from roboprobe.core.types import FailureClass, OracleResult, TaskSpec, Trace
from roboprobe.oracles._signals import clip, measured_speed
from roboprobe.oracles.base import Oracle

__all__ = ["ClearanceOracle"]


class ClearanceOracle(Oracle):
    """Footprint clearance; contact uses impact speed so rho stays informative."""

    id: ClassVar[str] = "O-CLEAR"
    failure_class: ClassVar[FailureClass] = FailureClass.COL
    severity: ClassVar[Literal["failure", "warning"]] = "failure"

    def evaluate(self, trace: Trace, task: TaskSpec) -> OracleResult:
        """Robustness from min clearance, or impact speed on first contact."""
        del task
        cfg = self.thresholds.clear
        d = trace.min_obstacle_dist
        contact = trace.contact | (d <= 0.0)
        min_d = float(np.min(d)) if trace.n_samples else float("inf")
        if trace.n_samples and np.any(contact):
            idx = int(np.argmax(contact))
            v_impact = float(measured_speed(trace)[idx])
            mag = float(
                clip(cfg.r_contact_base + (1.0 - cfg.r_contact_base) * v_impact / cfg.v_ref)
            )
            r = -mag
            return OracleResult(
                oracle_id=self.id,
                failure_class=FailureClass.COL,
                severity="failure",
                robustness=r,
                violated=True,
                first_violation_t=float(trace.t[idx]),
                details={"min_dist_m": min_d, "v_impact": v_impact},
            )
        r = float(clip(min_d / cfg.d_norm)) if trace.n_samples else 1.0
        near = trace.n_samples > 0 and min_d < cfg.d_safe
        first_near = None
        if near:
            first_near = float(trace.t[int(np.argmax(d < cfg.d_safe))])
        return OracleResult(
            oracle_id=self.id,
            failure_class=FailureClass.NEAR if near else FailureClass.COL,
            severity="warning" if near else "failure",
            robustness=r,
            violated=False,
            first_violation_t=first_near,
            details={"min_dist_m": min_d if trace.n_samples else 0.0},
        )
