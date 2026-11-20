"""FAIL iff rho < 0 on Hypothesis traces (T-039a)."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from tests.factories import make_trace
from tests.unit.oracles.conftest import FakeEpisode, make_task

from roboprobe.core.settings import OracleThresholds
from roboprobe.core.types import NavStatus, Verdict
from roboprobe.oracles import VerdictEngine, create_all

pytestmark = pytest.mark.property

ENGINE = VerdictEngine(create_all(OracleThresholds()))
TASK = make_task()
N = 60


@given(st.integers(min_value=0, max_value=2**32 - 1))
@settings(max_examples=1000, deadline=None)
def test_fail_iff_rho_negative(seed: int) -> None:
    rng = np.random.default_rng(seed)
    t = np.arange(N, dtype=np.float64) * 0.1
    x = np.cumsum(rng.normal(0.05, 0.02, size=N))
    x -= x[0]
    nav = np.full(N, NavStatus.ACTIVE, dtype=np.int8)
    if rng.random() < 0.3:
        nav[-1] = NavStatus.ABORTED
    elif rng.random() < 0.5:
        nav[-1] = NavStatus.SUCCEEDED
    contact = rng.random(N) < 0.02
    d = np.abs(rng.normal(0.4, 0.2, size=N))
    d[contact] = 0.0
    trace = make_trace(
        n=N,
        dt=0.1,
        t=t,
        gt_x=x,
        est_x=x + rng.normal(0.0, 0.05, size=N),
        cmd_v=np.clip(rng.normal(0.3, 0.1, size=N), 0.0, 1.0),
        meas_v=np.clip(rng.normal(0.3, 0.1, size=N), 0.0, 1.0),
        cmd_w=rng.normal(0.0, 0.4, size=N),
        meas_w=rng.normal(0.0, 0.2, size=N),
        min_obstacle_dist=d,
        contact=contact,
        roll=rng.normal(0.0, 0.05, size=N),
        pitch=rng.normal(0.0, 0.05, size=N),
        nav_status=nav,
        goal=(5.0, 0.0),
    )
    out = ENGINE.judge(FakeEpisode(trace), TASK)
    if out.verdict is Verdict.INVALID:
        assert out.robustness is None
        return
    assert out.robustness is not None
    assert (out.verdict is Verdict.FAIL) == (out.robustness < 0.0)
