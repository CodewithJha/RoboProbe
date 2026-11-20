"""O-OSC (T-038b; docs/08 §3.7)."""

from __future__ import annotations

import numpy as np
import pytest
from tests.factories import make_trace
from tests.unit.oracles.conftest import make_task

from roboprobe.core.settings import OracleThresholds
from roboprobe.oracles.oscillation import OscillationOracle

pytestmark = pytest.mark.unit


def test_quiet_command_passes() -> None:
    res = OscillationOracle(OracleThresholds()).evaluate(make_trace(n=50), make_task())
    assert res.robustness == pytest.approx(1.0)
    assert res.severity == "warning"
    assert not res.violated


def test_alternating_yaw_warns() -> None:
    n = 80
    w = 0.5 * np.where(np.arange(n) % 2 == 0, 1.0, -1.0)
    res = OscillationOracle(OracleThresholds()).evaluate(make_trace(n=n, cmd_w=w), make_task())
    assert res.violated
    assert res.robustness == pytest.approx(-1.0)
    assert res.severity == "warning"


def test_n_max_override() -> None:
    n = 20
    w = 0.5 * np.where(np.arange(n) % 2 == 0, 1.0, -1.0)
    oracle = OscillationOracle(
        OracleThresholds(osc={"window_s": 5.0, "omega_min": 0.3, "n_max": 100})
    )
    res = oracle.evaluate(make_trace(n=n, cmd_w=w), make_task())
    assert not res.violated
    assert res.robustness > 0.0
