"""O-STAB (T-038a; docs/08 §3.6)."""

from __future__ import annotations

import numpy as np
import pytest
from tests.factories import make_trace
from tests.unit.oracles.conftest import make_task

from roboprobe.core.settings import OracleThresholds
from roboprobe.oracles.stability import StabilityOracle

pytestmark = pytest.mark.unit


def test_level_is_one() -> None:
    res = StabilityOracle(OracleThresholds()).evaluate(make_trace(n=20), make_task())
    assert res.robustness == pytest.approx(1.0)
    assert not res.violated


def test_yaw_rate_violation() -> None:
    n = 20
    w = np.zeros(n)
    w[4] = 4.0
    res = StabilityOracle(OracleThresholds()).evaluate(make_trace(n=n, meas_w=w), make_task())
    assert res.violated
    assert res.robustness == pytest.approx(1.0 - 4.0 / 3.0)
    assert res.first_violation_t == pytest.approx(0.4)


def test_tilt_violation() -> None:
    n = 15
    roll = np.zeros(n)
    roll[3] = 0.7
    res = StabilityOracle(OracleThresholds()).evaluate(make_trace(n=n, roll=roll), make_task())
    assert res.violated
    assert res.robustness == pytest.approx(1.0 - 0.7 / 0.35)


def test_theta_override() -> None:
    n = 10
    oracle = StabilityOracle(OracleThresholds(stab={"theta_max": 1.0, "omega_max": 3.0}))
    res = oracle.evaluate(make_trace(n=n, roll=np.full(n, 0.4)), make_task())
    assert not res.violated
    assert res.robustness == pytest.approx(1.0 - 0.4)
