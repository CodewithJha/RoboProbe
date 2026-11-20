"""O-OSC — commanded yaw-rate oscillation (warning) (docs/08 §3.7).

Implements: FR-ORC-001, FR-ORC-002, FR-ORC-005
"""

from __future__ import annotations

from typing import ClassVar, Literal

import numpy as np

from roboprobe.core.types import FailureClass, OracleResult, TaskSpec, Trace
from roboprobe.oracles._signals import clip
from roboprobe.oracles.base import Oracle

__all__ = ["OscillationOracle"]


class OscillationOracle(Oracle):
    """Count sign changes of ``ω_cmd`` above ``omega_min`` inside any ``window_s``."""

    id: ClassVar[str] = "O-OSC"
    failure_class: ClassVar[FailureClass] = FailureClass.OSC
    severity: ClassVar[Literal["failure", "warning"]] = "warning"

    def evaluate(self, trace: Trace, task: TaskSpec) -> OracleResult:
        """Clip of (n_max - max window count) / n_max; never a FAIL."""
        del task
        cfg = self.thresholds.osc
        n_max = float(cfg.n_max)
        if trace.n_samples < 2:  # noqa: PLR2004
            return self._result(1.0, False, None, 0.0)
        w = trace.cmd_w
        loud = np.abs(w) > cfg.omega_min
        sign = np.sign(w)
        change = (sign[1:] * sign[:-1] < 0.0) & loud[1:] & loud[:-1]
        event_t = trace.t[1:][change]
        if event_t.size == 0:
            return self._result(1.0, False, None, 0.0)
        # For each event time, count events in (t - W, t].
        left = np.searchsorted(event_t, event_t - cfg.window_s, side="left")
        counts = np.arange(event_t.size) - left + 1
        max_count = float(np.max(counts))
        r = float(clip((n_max - max_count) / n_max))
        violated = max_count > n_max
        first = None
        if violated:
            first = float(event_t[int(np.argmax(counts > n_max))])
        return self._result(r, violated, first, max_count)

    def _result(
        self,
        r: float,
        violated: bool,
        first: float | None,
        max_count: float,
    ) -> OracleResult:
        return OracleResult(
            oracle_id=self.id,
            failure_class=self.failure_class,
            severity=self.severity,
            robustness=r,
            violated=violated,
            first_violation_t=first,
            details={"max_window_sign_changes": max_count},
        )
