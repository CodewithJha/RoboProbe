"""O-NAV (T-037c; docs/08 §3.5)."""

from __future__ import annotations

import numpy as np
import pytest
from tests.factories import make_trace
from tests.unit.oracles.conftest import make_task

from roboprobe.core.settings import OracleThresholds
from roboprobe.core.types import NavStatus
from roboprobe.oracles.nav import NavStatusOracle

pytestmark = pytest.mark.unit


def test_abort_before_goal() -> None:
    n = 20
    nav = np.full(n, NavStatus.ACTIVE, dtype=np.int8)
    nav[-1] = NavStatus.ABORTED
    x = np.zeros(n)
    res = NavStatusOracle(OracleThresholds()).evaluate(
        make_trace(n=n, gt_x=x, est_x=x.copy(), nav_status=nav, goal=(5.0, 0.0)),
        make_task(),
    )
    assert res.violated
    assert res.robustness == pytest.approx(-0.5)


def test_abort_after_goal_is_ok() -> None:
    n = 20
    nav = np.full(n, NavStatus.ACTIVE, dtype=np.int8)
    nav[-1] = NavStatus.ABORTED
    res = NavStatusOracle(OracleThresholds()).evaluate(
        make_trace(n=n, dt=0.1, speed=0.5, nav_status=nav, goal=(0.5, 0.0)),
        make_task(goal={"x": 0.5, "y": 0.0, "yaw": 0.0}),
    )
    assert not res.violated
    assert res.robustness == pytest.approx(1.0)


def test_r_abort_override() -> None:
    n = 10
    nav = np.full(n, NavStatus.ABORTED, dtype=np.int8)
    x = np.zeros(n)
    oracle = NavStatusOracle(OracleThresholds(nav={"r_abort": -0.25}))
    trace = make_trace(n=n, gt_x=x, est_x=x.copy(), nav_status=nav, goal=(5.0, 0.0))
    res = oracle.evaluate(trace, make_task())
    assert res.robustness == pytest.approx(-0.25)
