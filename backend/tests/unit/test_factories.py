"""Self-tests for :mod:`tests.factories` and the Hypothesis profiles in ``tests/conftest.py``."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError
from tests.factories import (
    DEFAULT_CLEARANCE_M,
    DEFAULT_DT_S,
    DEFAULT_SPEED_MPS,
    DEFAULT_TRACE_SAMPLES,
    make_observation,
    make_oracle_result,
    make_run_outcome,
    make_scenario,
    make_trace,
)

from roboprobe.core.types import NavStatus, Observation, Verdict

pytestmark = pytest.mark.unit

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "factory", [make_scenario, make_observation, make_oracle_result, make_run_outcome]
)
def test_model_factories_build_valid_frozen_models(factory: object) -> None:
    model = factory()  # type: ignore[operator]
    assert model.model_config["frozen"]
    with pytest.raises(ValidationError):
        model.model_copy().__setattr__("model_fields_set_probe", 1)
    type(model).model_validate(model.model_dump())


def test_overrides_are_applied_and_validated() -> None:
    scenario = make_scenario(space_id="other_space")
    assert scenario.space_id == "other_space"
    failing = make_observation(verdict=Verdict.INVALID, robustness=None)
    assert failing.verdict is Verdict.INVALID
    with pytest.raises(ValidationError):
        make_observation(verdict=Verdict.INVALID)  # robustness must be None for INVALID


def test_observation_run_ids_are_unique() -> None:
    first: Observation = make_observation()
    assert first.run_id != make_observation().run_id


def test_default_trace_is_a_successful_straight_line() -> None:
    trace = make_trace()
    assert trace.n_samples == DEFAULT_TRACE_SAMPLES
    assert trace.duration_s == pytest.approx((DEFAULT_TRACE_SAMPLES - 1) * DEFAULT_DT_S)
    np.testing.assert_allclose(trace.gt_x, DEFAULT_SPEED_MPS * trace.t)
    np.testing.assert_array_equal(trace.min_obstacle_dist, DEFAULT_CLEARANCE_M)
    assert not trace.contact.any()
    assert trace.nav_status[-1] == NavStatus.SUCCEEDED
    assert set(trace.nav_status[:-1]) == {NavStatus.ACTIVE}
    assert trace.goal_x == pytest.approx(trace.gt_x[-1])


def test_trace_parameters_and_column_overrides() -> None:
    n = 5
    contact = [False, False, True, False, False]
    trace = make_trace(n=n, dt=0.2, speed=1.0, goal=(3.0, 2.0), meta={"seed": 1}, contact=contact)
    np.testing.assert_allclose(trace.t, np.arange(n) * 0.2)
    np.testing.assert_array_equal(trace.contact, contact)
    assert trace.contact.dtype == np.bool_
    assert (trace.goal_x, trace.goal_y) == (3.0, 2.0)
    np.testing.assert_allclose(trace.gt_x[-1], 0.8)
    assert trace.meta == {"seed": 1}


def test_trace_rejects_unknown_columns_and_invalid_overrides() -> None:
    with pytest.raises(TypeError, match="unknown Trace column"):
        make_trace(not_a_column=[1.0])
    with pytest.raises(ValueError, match="length"):
        make_trace(n=3, min_obstacle_dist=[1.0, 2.0])


def test_empty_trace_is_valid() -> None:
    trace = make_trace(n=0)
    assert trace.n_samples == 0
    assert trace.goal_x == 0.0


@pytest.mark.parametrize(("profile", "expected"), [("ci", 200), ("nightly", 2000)])
def test_hypothesis_profile_is_selected_by_environment(profile: str, expected: int) -> None:
    script = (
        "import runpy, hypothesis; runpy.run_path('tests/conftest.py'); "
        "print(hypothesis.settings().max_examples)"
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter and inline script
        [sys.executable, "-c", script],
        cwd=BACKEND_DIR,
        env={**os.environ, "HYPOTHESIS_PROFILE": profile},
        capture_output=True,
        text=True,
        check=True,
    )
    assert int(result.stdout) == expected
