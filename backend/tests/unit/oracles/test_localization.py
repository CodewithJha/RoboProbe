"""O-LOC (T-037b; docs/08 §3.4)."""

from __future__ import annotations

import numpy as np
import pytest
from tests.factories import make_trace
from tests.unit.oracles.conftest import make_task

from roboprobe.core.settings import OracleThresholds
from roboprobe.oracles.localization import LocalizationOracle

pytestmark = pytest.mark.unit


def test_sustained_error_fails() -> None:
    n = 50
    x = np.linspace(0.0, 2.0, n)
    res = LocalizationOracle(OracleThresholds()).evaluate(
        make_trace(n=n, dt=0.1, gt_x=x, est_x=x + 1.0, goal=(2.0, 0.0)),
        make_task(),
    )
    assert res.violated
    assert res.robustness == pytest.approx(-1.0)


def test_short_spike_does_not_fail() -> None:
    n = 50
    x = np.linspace(0.0, 2.0, n)
    est = x.copy()
    est[10] = x[10] + 2.0
    res = LocalizationOracle(OracleThresholds()).evaluate(
        make_trace(n=n, dt=0.1, gt_x=x, est_x=est, goal=(2.0, 0.0)),
        make_task(),
    )
    assert not res.violated
    assert res.robustness > 0.0


def test_hold_override() -> None:
    n = 40
    x = np.zeros(n)
    est = np.full(n, 1.0)
    oracle = LocalizationOracle(OracleThresholds(loc={"e_max": 0.5, "hold_s": 0.0}))
    res = oracle.evaluate(make_trace(n=n, dt=0.1, gt_x=x, est_x=est, goal=(5.0, 0.0)), make_task())
    assert res.violated
