"""Unit tests for S-PROBE refine planner (T-059b, docs/07 §6.1)."""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pytest
from tests.factories import make_observation

from roboprobe.core.settings.selection import ProbeDefaults
from roboprobe.core.types import Verdict
from roboprobe.selection.refine import RefinePlan, RefineScheduler

pytestmark = pytest.mark.unit

BOUNDARY = 0.3


def _step_verdict(x: np.ndarray) -> Verdict:
    return Verdict.FAIL if float(x[0]) >= BOUNDARY else Verdict.PASS


def _obs(point: np.ndarray, verdict: Verdict) -> object:
    rho = -0.2 if verdict is Verdict.FAIL else 0.2
    return make_observation(
        x_unit=tuple(float(v) for v in point),
        verdict=verdict,
        robustness=rho,
        run_id=uuid4(),
    )


def test_bisection_converges_within_two_pow_neg_steps() -> None:
    defaults = ProbeDefaults()
    steps = defaults.refine_bisect_steps
    plan = RefinePlan(
        medoid=np.array([1.0]),
        nominal=np.array([0.0]),
        bisect_steps=steps,
        perturb_n=0,
        seed=0,
    )
    history: list[object] = []
    for _ in range(steps):
        point = plan.next_point(history)  # type: ignore[arg-type]
        assert point is not None
        verdict = _step_verdict(point)
        history.append(_obs(point, verdict))
        assert plan.next_point([]) is None  # awaiting
    assert plan.next_point(history) is None  # type: ignore[arg-type]
    assert plan.done
    assert abs(float(plan.closest_failing[0]) - BOUNDARY) <= 2.0 ** (-steps)


def test_perturbations_deterministic_and_in_bounds() -> None:
    defaults = ProbeDefaults()
    medoid = np.array([0.2, 0.8, 0.5])
    a = RefinePlan(
        medoid,
        nominal=np.zeros(3),
        bisect_steps=0,
        perturb_n=defaults.refine_perturb_n,
        perturb_std=defaults.refine_perturb_std,
        seed=11,
    )
    b = RefinePlan(
        medoid,
        nominal=np.zeros(3),
        bisect_steps=0,
        perturb_n=defaults.refine_perturb_n,
        perturb_std=defaults.refine_perturb_std,
        seed=11,
    )
    points_a = [a.next_point([]) for _ in range(defaults.refine_perturb_n)]
    points_b = [b.next_point([]) for _ in range(defaults.refine_perturb_n)]
    assert a.done and b.done
    for pa, pb in zip(points_a, points_b, strict=True):
        assert pa is not None and pb is not None
        np.testing.assert_allclose(pa, pb)
        assert np.all((pa >= 0.0) & (pa <= 1.0))


def test_oldest_unrefined_mode_first() -> None:
    sched = RefineScheduler(nominal=np.zeros(2), bisect_steps=1, perturb_n=0, seed=0)
    sched.add_mode(np.array([1.0, 0.0]), mode_key="old")
    sched.add_mode(np.array([0.0, 1.0]), mode_key="new")
    first = sched.next_point([])
    assert first is not None
    np.testing.assert_allclose(first, np.array([0.5, 0.0]))
    # Still awaiting old mode — do not advance to newer mode.
    assert sched.next_point([]) is None
    history = [_obs(first, Verdict.FAIL)]
    second = sched.next_point(history)  # type: ignore[arg-type]
    assert second is not None
    np.testing.assert_allclose(second, np.array([0.0, 0.5]))


def test_state_dict_round_trip_reproduces_next_point() -> None:
    defaults = ProbeDefaults()
    plan = RefinePlan(
        medoid=np.array([0.9, 0.1]),
        nominal=np.array([0.1, 0.1]),
        bisect_steps=0,
        perturb_n=defaults.refine_perturb_n,
        seed=3,
    )
    first = plan.next_point([])
    assert first is not None
    clone = RefinePlan(np.zeros(2), np.zeros(2))
    clone.load_state_dict(plan.state_dict())
    rest = [clone.next_point([]) for _ in range(defaults.refine_perturb_n - 1)]
    original = [plan.next_point([]) for _ in range(defaults.refine_perturb_n - 1)]
    for a, b in zip(rest, original, strict=True):
        assert a is not None and b is not None
        np.testing.assert_allclose(a, b)
