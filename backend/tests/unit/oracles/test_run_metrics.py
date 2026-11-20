"""compute_run_metrics (T-039a; docs/08 §6)."""

from __future__ import annotations

import pytest
from tests.factories import make_trace
from tests.fixtures.traces.make_golden_traces import straight_pass
from tests.unit.oracles.conftest import make_task

from roboprobe.oracles.metrics import compute_run_metrics

pytestmark = pytest.mark.unit


def test_straight_pass_metrics() -> None:
    trace = straight_pass()
    m = compute_run_metrics(trace, make_task())
    assert m["duration_s"] == pytest.approx(10.0)
    assert m["path_length_m"] == pytest.approx(5.0)
    assert m["mean_speed"] == pytest.approx(0.5)
    assert m["max_speed"] == pytest.approx(0.5)
    assert m["min_clearance_m"] == pytest.approx(1.0)
    assert m["time_below_d_safe_s"] == pytest.approx(0.0)
    assert m["max_loc_error_m"] == pytest.approx(0.0)
    assert m["goal_reached"] == pytest.approx(1.0)
    assert m["t_goal_s"] == pytest.approx(9.5)
    assert m["energy_proxy"] == pytest.approx(0.5**2 * 10.0)
    assert m["rtf_mean"] == pytest.approx(-1.0)


def test_empty_trace_metrics() -> None:
    m = compute_run_metrics(make_trace(n=0), make_task())
    assert m["duration_s"] == 0.0
    assert m["t_goal_s"] == pytest.approx(-1.0)
