"""O-LOC — sustained localisation divergence (docs/08 §3.4).

Implements: FR-ORC-001, FR-ORC-002, FR-ORC-005
"""

from __future__ import annotations

from typing import ClassVar, Literal

import numpy as np
import numpy.typing as npt

from roboprobe.core.types import FailureClass, OracleResult, TaskSpec, Trace
from roboprobe.oracles._signals import clip, loc_error_m
from roboprobe.oracles.base import Oracle

__all__ = ["LocalizationOracle"]


class LocalizationOracle(Oracle):
    """Error must persist for ``hold_s``; spikes shorter than H do not violate."""

    id: ClassVar[str] = "O-LOC"
    failure_class: ClassVar[FailureClass] = FailureClass.LOC
    severity: ClassVar[Literal["failure", "warning"]] = "failure"

    def evaluate(self, trace: Trace, task: TaskSpec) -> OracleResult:
        """Clip of (e_max - max sustained error) / e_max."""
        del task
        cfg = self.thresholds.loc
        if trace.n_samples == 0:
            return self._result(1.0, False, None, 0.0)
        err = loc_error_m(trace)
        hold = cfg.hold_s
        t_end = trace.t[-1]
        full = trace.t + hold <= t_end + 1e-15
        if not np.any(full):
            e_s_max = float(np.min(err))
            r = float(clip((cfg.e_max - e_s_max) / cfg.e_max))
            return self._result(r, e_s_max > cfg.e_max, None, e_s_max)
        # e_s[i] = min err on [t[i], t[i]+H] via reversed running minimum + searchsorted
        e_s = _forward_window_min(trace.t, err, hold)
        e_s_max = float(np.max(e_s[full]))
        r = float(clip((cfg.e_max - e_s_max) / cfg.e_max))
        violated = e_s_max > cfg.e_max
        first = None
        if violated:
            bad = full & (e_s > cfg.e_max)
            first = float(trace.t[int(np.argmax(bad))])
        return self._result(r, violated, first, e_s_max)

    def _result(
        self,
        r: float,
        violated: bool,
        first: float | None,
        e_s_max: float,
    ) -> OracleResult:
        return OracleResult(
            oracle_id=self.id,
            failure_class=self.failure_class,
            severity=self.severity,
            robustness=r,
            violated=violated,
            first_violation_t=first,
            details={"max_sustained_error_m": e_s_max},
        )


def _forward_window_min(
    t: np.ndarray,
    err: np.ndarray,
    hold: float,
) -> npt.NDArray[np.float64]:
    """``e_s[i] = min err[j]`` for ``t[i] ≤ t[j] ≤ t[i]+hold`` (vectorised)."""
    n = t.size
    # For each i, right = last index with t[right] <= t[i]+hold
    right = np.searchsorted(t, t + hold, side="right") - 1
    # Range-min via sparse table (log n)
    logn = int(np.floor(np.log2(n))) + 1
    st = np.empty((logn, n), dtype=np.float64)
    st[0] = err
    lengths = 1 << np.arange(logn)
    for k in range(1, logn):
        span = lengths[k]
        st[k, : n - span + 1] = np.minimum(st[k - 1, : n - span + 1], st[k - 1, span - 1 : n])
        if n - span + 1 < n:
            st[k, n - span + 1 :] = st[k - 1, n - span + 1 :]
    width = np.maximum(right - np.arange(n) + 1, 1)
    k = np.floor(np.log2(width)).astype(np.intp)
    i0 = np.arange(n)
    a = st[k, i0]
    b = st[k, right - (1 << k) + 1]
    return np.asarray(np.minimum(a, b), dtype=np.float64)
