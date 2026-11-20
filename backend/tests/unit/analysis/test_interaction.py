"""Tests for :mod:`roboprobe.analysis.interaction` (T-074a, docs/09 §6)."""

from __future__ import annotations

from itertools import combinations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tests.unit.analysis.conftest import make_run, uid

from roboprobe.analysis.interaction import InteractionTester
from roboprobe.analysis.types import AnalysisRun, FailureModeSummary, ParamRange
from roboprobe.core.settings.analysis import InteractionSettings
from roboprobe.core.types import FailureClass, Verdict

pytestmark = pytest.mark.unit


def _mode(params: tuple[str, ...], values: dict[str, float]) -> FailureModeSummary:
    ranges = {pid: ParamRange(unit="-", q05=0.0, q95=0.1, space_coverage=0.1) for pid in params}
    return FailureModeSummary(
        code="FM-01",
        size=5,
        primary_class=FailureClass.COL,
        class_mix={FailureClass.COL: 1.0},
        ranges=ranges,
        characteristic=frozenset(params),
        medoid_run_id=uid(1),
        minimal_run_id=uid(1),
        minimal_values=values,
        member_run_ids=(uid(1),),
        label="x",
        provisional=False,
    )


def _plan_size(n_c: int, repeats: int) -> int:
    pairs = len(list(combinations(range(n_c), 2))) if n_c >= 3 else 0
    return (n_c + pairs + 1) * repeats


def test_plan_size_and_seeds(space: object) -> None:
    values = dict(space.nominal_values())  # type: ignore[union-attr]
    values["robot.max_speed"] = 0.45
    values["env.illuminance"] = 10.0
    values["sensor.lidar_noise_std"] = 0.08
    mode = _mode(
        ("robot.max_speed", "env.illuminance", "sensor.lidar_noise_std"),
        values,
    )
    settings = InteractionSettings(repeats=3, success_ratio=0.67)
    planned = InteractionTester(settings, campaign_seed=42).plan(mode, space)  # type: ignore[arg-type]
    assert len(planned) == _plan_size(3, 3)
    seeds = [p.seed for p in planned]
    assert len(set(seeds)) == len(seeds)
    again = InteractionTester(settings, campaign_seed=42).plan(mode, space)  # type: ignore[arg-type]
    assert [p.seed for p in again] == seeds
    assert all("confirm" in p.tags for p in planned)


def test_three_way_interaction_confirmed() -> None:
    params = ("robot.max_speed", "env.illuminance", "sensor.lidar_noise_std")
    mode = _mode(params, {})
    tester = InteractionTester(InteractionSettings(repeats=3, success_ratio=0.67), 1)
    runs: list[AnalysisRun] = []
    for subset, fail in (
        (frozenset({"robot.max_speed"}), False),
        (frozenset({"env.illuminance"}), False),
        (frozenset({"sensor.lidar_noise_std"}), False),
        (frozenset(), True),
    ):
        for _ in range(3):
            runs.append(
                make_run(
                    verdict=Verdict.FAIL if fail else Verdict.PASS,
                    primary_failure=FailureClass.COL if fail else None,
                    subset=subset,
                )
            )
    verdict = tester.conclude(mode, runs)
    assert verdict.status == "CONFIRMED"
    assert verdict.order is None or verdict.order >= 2


def test_single_factor_not_interaction() -> None:
    mode = _mode(("robot.max_speed",), {})
    tester = InteractionTester(InteractionSettings(repeats=3, success_ratio=0.67), 1)
    runs = [
        make_run(verdict=Verdict.FAIL, subset=frozenset({"robot.max_speed"})) for _ in range(3)
    ] + [make_run(verdict=Verdict.FAIL, subset=frozenset()) for _ in range(3)]
    verdict = tester.conclude(mode, runs)
    assert verdict.status == "NOT_INTERACTION"


def test_inconclusive_invalid() -> None:
    mode = _mode(("robot.max_speed",), {})
    tester = InteractionTester(InteractionSettings(repeats=3, success_ratio=0.67), 1)
    runs = [
        make_run(verdict=Verdict.INVALID, primary_failure=None, subset=frozenset()),
        make_run(verdict=Verdict.FAIL, subset=frozenset()),
    ]
    assert tester.conclude(mode, runs).status == "INCONCLUSIVE"


@pytest.mark.parametrize(
    ("full_fail", "single_fail", "invalid", "expected"),
    [
        (True, False, False, "CONFIRMED"),
        (True, True, False, "NOT_INTERACTION"),
        (False, False, False, "NOT_INTERACTION"),
        (True, False, True, "INCONCLUSIVE"),
    ],
)
def test_conclude_table(full_fail: bool, single_fail: bool, invalid: bool, expected: str) -> None:
    mode = _mode(("a", "b"), {})
    tester = InteractionTester(InteractionSettings(repeats=3, success_ratio=0.67), 0)
    runs: list[AnalysisRun] = []
    for subset, fail in (
        (frozenset({"a"}), single_fail),
        (frozenset({"b"}), False),
        (frozenset(), full_fail),
    ):
        for i in range(3):
            if invalid and subset == frozenset() and i == 0:
                runs.append(make_run(verdict=Verdict.INVALID, primary_failure=None, subset=subset))
            else:
                runs.append(
                    make_run(
                        verdict=Verdict.FAIL if fail else Verdict.PASS,
                        primary_failure=FailureClass.COL if fail else None,
                        subset=subset,
                    )
                )
    assert tester.conclude(mode, runs).status == expected


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(n_c=st.integers(1, 4), repeats=st.integers(1, 4))
def test_plan_size_property(space: object, n_c: int, repeats: int) -> None:
    ids = [spec.id for spec in space.params][:n_c]  # type: ignore[union-attr]
    values = dict(space.nominal_values())  # type: ignore[union-attr]
    mode = _mode(tuple(ids), values)
    planned = InteractionTester(InteractionSettings(repeats=repeats), 0).plan(mode, space)  # type: ignore[arg-type]
    assert len(planned) == _plan_size(n_c, repeats)
