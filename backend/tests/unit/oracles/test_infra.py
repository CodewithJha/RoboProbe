"""InfraCheck validity gate (T-036a; docs/08 §3.8)."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from tests.factories import make_trace
from tests.unit.oracles.conftest import DT, make_task

from roboprobe.core.settings import OracleThresholds
from roboprobe.core.types import FailureClass, NavStatus
from roboprobe.oracles.infra import (
    REASON_BACKEND,
    REASON_GAP,
    REASON_RTF,
    REASON_SHORT,
    REASON_SPAWN,
    REASON_STARTUP,
    InfraCheck,
)

pytestmark = pytest.mark.unit

FR_RUN_004_GAP_S = 0.2  # SRS AC; not the InfraCheck default
SPEC_DEFAULT_GAP_S = 1.0


def _check(thresholds: OracleThresholds | None = None, **kwargs: object) -> InfraCheck:
    return InfraCheck(thresholds or OracleThresholds(), **kwargs)


def _ok_trace(*, gap: float = DT, n: int = 60, **cols: object):
    t = np.cumsum(np.concatenate([[0.0], np.full(n - 1, gap)])) if n else np.array([])
    rtf = cols.pop("rtf", None)
    trace = make_trace(n=n, dt=DT, t=t, **cols)
    if rtf is not None:
        return replace(trace, rtf=np.asarray(rtf, dtype=np.float32))
    return trace


def test_pass_on_healthy_trace() -> None:
    assert _check().evaluate(_ok_trace(), make_task()) is None


def test_backend_infra_error() -> None:
    res = _check().evaluate(_ok_trace(), make_task(), infra_error="gz crash")
    assert res is not None
    assert res.failure_class is FailureClass.INFRA
    assert res.details["reason"] == REASON_BACKEND


def test_short_trace_not_at_goal() -> None:
    res = _check().evaluate(make_trace(n=10, dt=DT), make_task())
    assert res is not None
    assert res.details["reason"] == REASON_SHORT


def test_short_trace_at_goal_is_valid() -> None:
    task = make_task(goal={"x": 0.45, "y": 0.0, "yaw": 0.0})
    trace = make_trace(n=5, dt=DT, speed=0.5, goal=(0.45, 0.0))
    assert _check().evaluate(trace, task) is None


def test_default_gap_is_spec_1s_not_fr_run_004() -> None:
    thresholds = OracleThresholds()
    assert thresholds.infra.max_gap_s == SPEC_DEFAULT_GAP_S
    check = _check(thresholds)
    assert check.max_gap_s == SPEC_DEFAULT_GAP_S
    mid = 0.5  # > 0.2 s (FR-RUN-004) and < 1.0 s (docs/08 default)
    trace = _ok_trace(gap=mid, n=20)
    assert check.evaluate(trace, make_task()) is None
    strict = _check(max_gap_s=FR_RUN_004_GAP_S)
    res = strict.evaluate(trace, make_task())
    assert res is not None
    assert res.details["reason"] == REASON_GAP


def test_gap_above_default_flags() -> None:
    trace = _ok_trace(gap=1.5, n=20)
    res = _check().evaluate(trace, make_task())
    assert res is not None
    assert res.details["reason"] == REASON_GAP


def test_low_rtf() -> None:
    n = 60
    rtf = np.full(n, 0.05, dtype=np.float32)
    res = _check().evaluate(_ok_trace(n=n, rtf=rtf), make_task())
    assert res is not None
    assert res.details["reason"] == REASON_RTF


def test_rtf_none_is_kinematic_ok() -> None:
    assert _ok_trace().rtf is None
    assert _check().evaluate(_ok_trace(), make_task()) is None


def test_nav_startup_timeout() -> None:
    n = 60
    nav = np.full(n, NavStatus.IDLE, dtype=np.int8)
    thresholds = OracleThresholds(infra={"startup_timeout_s": 1.0})
    res = _check(thresholds).evaluate(_ok_trace(n=n, nav_status=nav), make_task())
    assert res is not None
    assert res.details["reason"] == REASON_STARTUP


def test_spawn_pose_error() -> None:
    n = 60
    x = np.full(n, 5.0)
    res = _check().evaluate(_ok_trace(n=n, gt_x=x, est_x=x.copy()), make_task())
    assert res is not None
    assert res.details["reason"] == REASON_SPAWN


def test_reason_codes_are_distinct() -> None:
    codes = {REASON_BACKEND, REASON_SHORT, REASON_GAP, REASON_RTF, REASON_STARTUP, REASON_SPAWN}
    assert len(codes) == 6
