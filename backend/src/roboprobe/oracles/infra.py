"""InfraCheck — run validity gate (docs/08 §3.8). F-INFRA is never a robot failure.

Implements: FR-ORC-003
"""

from __future__ import annotations

from typing import Final

import numpy as np

from roboprobe.core.settings import OracleThresholds
from roboprobe.core.types import FailureClass, NavStatus, OracleResult, TaskSpec, Trace
from roboprobe.oracles._signals import P1_NOMINAL_MAX_SPEED_MPS, at_goal
from roboprobe.scenario.task import time_limit_s

__all__ = ["DOC_SHORT_TRACE_S", "InfraCheck"]

# docs/08 §3.8: duration < min(5 s, T_max) while not at goal. Not a campaign threshold.
DOC_SHORT_TRACE_S: Final[float] = 5.0

REASON_BACKEND: Final = "backend_infra_error"
REASON_SHORT: Final = "short_trace"
REASON_GAP: Final = "sampling_gap"
REASON_RTF: Final = "low_rtf"
REASON_STARTUP: Final = "nav_startup"
REASON_SPAWN: Final = "spawn_pose"


class InfraCheck:
    """Validity gate; runs before failure oracles (docs/08 §5).

    ``max_gap_s`` defaults to ``oracles.infra.max_gap_s`` (1.0 s, docs/08 §4 / 27 §4.6).
    FR-RUN-004's 0.2 s gap is the recording AC; pass a tighter ``max_gap_s`` to enforce it.
    """

    id = "O-INFRA"
    failure_class = FailureClass.INFRA

    def __init__(
        self,
        thresholds: OracleThresholds,
        *,
        max_gap_s: float | None = None,
        short_trace_s: float | None = None,
    ) -> None:
        """Inject infra thresholds; optional ``max_gap_s`` overrides the spec default."""
        self.thresholds = thresholds
        self.max_gap_s = thresholds.infra.max_gap_s if max_gap_s is None else max_gap_s
        self.short_trace_s = DOC_SHORT_TRACE_S if short_trace_s is None else short_trace_s

    def evaluate(
        self,
        trace: Trace,
        task: TaskSpec,
        *,
        infra_error: str | None = None,
        max_speed_mps: float = P1_NOMINAL_MAX_SPEED_MPS,
    ) -> OracleResult | None:
        """Return an F-INFRA result if invalid, else ``None``.

        ``max_speed_mps`` is P1's default (docs/06) used only to compute ``T_max``.
        """
        path = float(np.hypot(task.goal.x - task.start.x, task.goal.y - task.start.y))
        t_max = time_limit_s(task, max_speed_mps, path)
        reason, detail = self._first_reason(trace, task, infra_error, t_max)
        if reason is None:
            return None
        return OracleResult(
            oracle_id=self.id,
            failure_class=self.failure_class,
            severity="failure",
            robustness=-1.0,
            violated=True,
            first_violation_t=float(trace.t[0]) if trace.n_samples else 0.0,
            details={"reason": reason, **detail},
        )

    def _first_reason(
        self,
        trace: Trace,
        task: TaskSpec,
        infra_error: str | None,
        t_max: float,
    ) -> tuple[str | None, dict[str, float | str]]:
        infra = self.thresholds.infra
        reached = bool(np.any(at_goal(trace, task))) if trace.n_samples else False
        min_dur = min(self.short_trace_s, t_max)
        gap = float(np.max(np.diff(trace.t))) if trace.n_samples >= 2 else 0.0  # noqa: PLR2004
        mean_rtf = float(np.mean(trace.rtf)) if trace.rtf is not None and trace.n_samples else 1.0
        t_active_s = 0.0
        spawn = 0.0
        if trace.n_samples:
            active = trace.nav_status == np.int8(NavStatus.ACTIVE)
            t0 = float(trace.t[0])
            if np.any(active):
                t_active = float(trace.t[int(np.argmax(active))])
            else:
                t_active = float(trace.t[-1]) + 1.0
            t_active_s = t_active - t0
            spawn = float(np.hypot(trace.gt_x[0] - task.start.x, trace.gt_y[0] - task.start.y))
        candidates: tuple[tuple[bool, str, dict[str, float | str]], ...] = (
            (bool(infra_error), REASON_BACKEND, {"backend_error": infra_error or ""}),
            (
                trace.duration_s < min_dur and not reached,
                REASON_SHORT,
                {"duration_s": trace.duration_s, "min_duration_s": min_dur},
            ),
            (
                gap > self.max_gap_s,
                REASON_GAP,
                {"max_gap_s_observed": gap, "max_gap_s": self.max_gap_s},
            ),
            (
                trace.rtf is not None and trace.n_samples > 0 and mean_rtf < infra.min_rtf,
                REASON_RTF,
                {"mean_rtf": mean_rtf, "min_rtf": infra.min_rtf},
            ),
            (
                trace.n_samples > 0 and t_active_s > infra.startup_timeout_s,
                REASON_STARTUP,
                {"t_active_s": t_active_s, "startup_timeout_s": infra.startup_timeout_s},
            ),
            (
                trace.n_samples > 0 and spawn > infra.spawn_tolerance_m,
                REASON_SPAWN,
                {"spawn_error_m": spawn, "spawn_tolerance_m": infra.spawn_tolerance_m},
            ),
        )
        for cond, reason, detail in candidates:
            if cond:
                return reason, detail
        return None, {}
