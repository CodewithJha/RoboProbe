"""O-CLEAR (T-036b; docs/08 §3.1)."""

from __future__ import annotations

import numpy as np
import pytest
from tests.factories import make_trace
from tests.unit.oracles.conftest import make_task

from roboprobe.core.settings import OracleThresholds
from roboprobe.core.types import FailureClass
from roboprobe.oracles.clearance import ClearanceOracle

pytestmark = pytest.mark.unit


def test_no_contact_normalises_min_distance() -> None:
    n = 20
    oracle = ClearanceOracle(OracleThresholds())
    trace = make_trace(n=n, min_obstacle_dist=np.full(n, 0.25))
    res = oracle.evaluate(trace, make_task())
    assert res.robustness == pytest.approx(0.5)
    assert not res.violated
    assert res.failure_class is FailureClass.COL


def test_near_miss_warning() -> None:
    n = 20
    d = np.full(n, 1.0)
    d[5] = 0.05
    res = ClearanceOracle(OracleThresholds()).evaluate(
        make_trace(n=n, min_obstacle_dist=d), make_task()
    )
    assert res.failure_class is FailureClass.NEAR
    assert res.severity == "warning"
    assert not res.violated
    assert res.robustness == pytest.approx(0.1)
    assert res.first_violation_t == pytest.approx(0.5)


def test_contact_uses_impact_speed() -> None:
    n = 20
    contact = np.zeros(n, dtype=np.bool_)
    contact[10] = True
    v = np.full(n, 0.25)
    res = ClearanceOracle(OracleThresholds()).evaluate(
        make_trace(n=n, contact=contact, meas_v=v, min_obstacle_dist=np.full(n, 1.0)),
        make_task(),
    )
    want = -(0.1 + 0.9 * 0.25 / 0.5)
    assert res.robustness == pytest.approx(want)
    assert res.violated
    assert res.failure_class is FailureClass.COL
    assert res.first_violation_t == pytest.approx(1.0)


def test_threshold_override() -> None:
    n = 10
    oracle = ClearanceOracle(OracleThresholds(clear={"d_norm": 0.25}))
    res = oracle.evaluate(make_trace(n=n, min_obstacle_dist=np.full(n, 0.25)), make_task())
    assert res.robustness == pytest.approx(1.0)


def test_monotonic_clearance() -> None:
    n = 15
    lo = ClearanceOracle(OracleThresholds()).evaluate(
        make_trace(n=n, min_obstacle_dist=np.full(n, 0.2)), make_task()
    )
    hi = ClearanceOracle(OracleThresholds()).evaluate(
        make_trace(n=n, min_obstacle_dist=np.full(n, 0.4)), make_task()
    )
    assert hi.robustness >= lo.robustness


def test_time_shift_invariant() -> None:
    n = 20
    d = np.linspace(0.4, 0.8, n)
    a = make_trace(n=n, min_obstacle_dist=d)
    b = make_trace(n=n, t=a.t + 3.0, min_obstacle_dist=d)
    oracle = ClearanceOracle(OracleThresholds())
    assert oracle.evaluate(a, make_task()).robustness == oracle.evaluate(b, make_task()).robustness
