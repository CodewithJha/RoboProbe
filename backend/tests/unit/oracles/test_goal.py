"""O-GOAL (T-036c; docs/08 §3.2)."""

from __future__ import annotations

import numpy as np
import pytest
from tests.factories import make_trace
from tests.unit.oracles.conftest import make_task

from roboprobe.core.settings import OracleThresholds
from roboprobe.oracles.goal import GoalOracle

pytestmark = pytest.mark.unit


def test_reached_uses_leftover_time() -> None:
    n = 21
    task = make_task(
        goal={"x": 1.0, "y": 0.0, "yaw": 0.0},
        time_limit={"factor": 100.0, "offset_s": 0.0, "cap_s": 10.0},
    )
    trace = make_trace(n=n, dt=0.1, speed=0.5, goal=(1.0, 0.0))
    res = GoalOracle(OracleThresholds()).evaluate(trace, task)
    t_goal = 1.5  # first x = 0.75 meets |x-1| ≤ 0.25
    assert res.robustness == pytest.approx((10.0 - t_goal) / 10.0)
    assert not res.violated


def test_missed_uses_remaining_path() -> None:
    n = 20
    task = make_task(
        goal={"x": 10.0, "y": 0.0, "yaw": 0.0},
        time_limit={"factor": 100.0, "offset_s": 0.0, "cap_s": 1.0},
    )
    trace = make_trace(n=n, dt=0.1, speed=0.5, goal=(10.0, 0.0))
    res = GoalOracle(OracleThresholds()).evaluate(trace, task)
    assert res.violated
    last_x = 0.5 * (n - 1) * 0.1
    d_rem = 10.0 - last_x
    assert res.robustness == pytest.approx(-d_rem / 10.0)


def test_r_min_floor() -> None:
    n = 5
    task = make_task(
        goal={"x": 100.0, "y": 0.0, "yaw": 0.0},
        start={"x": 0.0, "y": 0.0, "yaw": 0.0},
        goal_tolerance={"xy": 0.01, "yaw": 0.5},
        time_limit={"factor": 1.0, "offset_s": 0.0, "cap_s": 0.1},
    )
    gt_x = np.full(n, 99.5)
    oracle = GoalOracle(OracleThresholds(goal={"r_min": 0.2}))
    trace = make_trace(n=n, dt=0.1, gt_x=gt_x, est_x=gt_x.copy(), goal=(100.0, 0.0))
    res = oracle.evaluate(trace, task)
    assert res.violated
    assert res.robustness == pytest.approx(-0.2)
