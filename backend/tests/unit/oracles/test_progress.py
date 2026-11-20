"""O-PROG (T-037a; docs/08 §3.3)."""

from __future__ import annotations

import numpy as np
import pytest
from tests.factories import make_trace
from tests.unit.oracles.conftest import make_task

from roboprobe.core.settings import OracleThresholds
from roboprobe.core.types import NavStatus
from roboprobe.oracles.progress import ProgressOracle

pytestmark = pytest.mark.unit


def test_frozen_pose_is_stuck() -> None:
    n = 121
    x = np.zeros(n)
    nav = np.full(n, NavStatus.ACTIVE, dtype=np.int8)
    res = ProgressOracle(OracleThresholds()).evaluate(
        make_trace(n=n, dt=0.1, gt_x=x, est_x=x.copy(), nav_status=nav, goal=(5.0, 0.0)),
        make_task(),
    )
    assert res.violated
    assert res.robustness == pytest.approx(-0.1)
    assert res.first_violation_t == pytest.approx(10.0)


def test_moving_is_not_stuck() -> None:
    n = 121
    res = ProgressOracle(OracleThresholds()).evaluate(
        make_trace(n=n, dt=0.1, speed=0.5, goal=(6.0, 0.0)),
        make_task(goal={"x": 6.0, "y": 0.0, "yaw": 0.0}),
    )
    assert not res.violated
    assert res.robustness == pytest.approx(1.0)


def test_window_override() -> None:
    n = 40
    x = np.zeros(n)
    nav = np.full(n, NavStatus.ACTIVE, dtype=np.int8)
    cfg = OracleThresholds(prog={"window_s": 2.0, "delta_min": 0.05, "delta_norm": 0.5})
    res = ProgressOracle(cfg).evaluate(
        make_trace(n=n, dt=0.1, gt_x=x, est_x=x.copy(), nav_status=nav, goal=(5.0, 0.0)),
        make_task(),
    )
    assert res.violated
    assert res.first_violation_t == pytest.approx(2.0)
