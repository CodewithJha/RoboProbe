"""Unit and property tests for :mod:`roboprobe.core.types` (docs/05 §1)."""

from __future__ import annotations

import math
import pickle
from typing import Any, get_args
from uuid import UUID

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from roboprobe.core import types as core_types
from roboprobe.core.types import (
    CampaignStatus,
    FailureClass,
    NavStatus,
    Observation,
    OracleResult,
    ParamType,
    Phase,
    Pose2D,
    Proposal,
    RunOutcome,
    RunStatus,
    Scenario,
    SutProfile,
    TaskSpec,
    Trace,
    Verdict,
)

pytestmark = pytest.mark.unit

RUN_ID = UUID("01930000-0000-7000-8000-000000000001")


def make_scenario(**overrides: Any) -> Scenario:
    data: dict[str, Any] = {
        "space_id": "warehouse_v1",
        "space_version": "3f9a1c2b7d10",
        "values": {"robot.max_speed": 0.31, "env.n_people": 2, "env.layout": "narrow"},
        "scenario_hash": "a1b2c3",
    }
    return Scenario(**(data | overrides))


def make_oracle_result(**overrides: Any) -> OracleResult:
    data: dict[str, Any] = {
        "oracle_id": "O-CLEAR",
        "failure_class": FailureClass.COL,
        "severity": "failure",
        "robustness": -0.2,
        "violated": True,
        "first_violation_t": 12.5,
        "details": {"min_dist_m": 0.0, "where": "aisle"},
    }
    return OracleResult(**(data | overrides))


def make_task(**overrides: Any) -> TaskSpec:
    data: dict[str, Any] = {
        "schema_version": 1,
        "id": "warehouse_delivery_v1",
        "world": {"kinematic2d": "worlds/warehouse_k2d.json"},
        "map": "maps/warehouse.yaml",
        "start": {"x": 2.12, "y": -21.3, "yaw": 1.57},
        "goal": {"x": 2.0, "y": -8.0, "yaw": 1.57},
        "goal_tolerance": {"xy": 0.25, "yaw": 0.5},
        "nominal_path": "paths/warehouse_delivery_v1.csv",
        "injected_obstacles": [
            {
                "model": "dropped_pallet",
                "size": [0.8, 0.6, 0.15],
                "placement": {
                    "along": "obstacle.along_path",
                    "lateral": "obstacle.clearance",
                    "side": "left",
                },
            }
        ],
        "time_limit": {"factor": 2.5, "offset_s": 10, "cap_s": 120},
    }
    return TaskSpec.model_validate(data | overrides)


def trace_columns(n: int = 5) -> dict[str, Any]:
    cols: dict[str, Any] = {
        name: np.zeros(n, dtype=np.float64)
        for name in (
            "gt_x", "gt_y", "gt_yaw", "est_x", "est_y", "est_yaw", "cmd_v", "cmd_w",
            "meas_v", "meas_w", "min_obstacle_dist", "roll", "pitch",
        )
    }  # fmt: skip
    cols["t"] = np.arange(n, dtype=np.float64) * 0.1
    cols["contact"] = np.zeros(n, dtype=np.bool_)
    cols["nav_status"] = np.full(n, NavStatus.ACTIVE, dtype=np.int8)
    return cols


def make_trace(n: int = 5, **overrides: Any) -> Trace:
    return Trace(**(trace_columns(n) | {"goal_x": 1.0, "goal_y": 2.0} | overrides))


# --------------------------------------------------------------------------- enums


@pytest.mark.parametrize(
    ("member", "value"),
    [
        (FailureClass.COL, "F-COL"),
        (FailureClass.NEAR, "F-NEAR"),
        (FailureClass.TIMEOUT, "F-TIMEOUT"),
        (FailureClass.STUCK, "F-STUCK"),
        (FailureClass.LOC, "F-LOC"),
        (FailureClass.PLAN, "F-PLAN"),
        (FailureClass.INST, "F-INST"),
        (FailureClass.OSC, "F-OSC"),
        (FailureClass.INFRA, "F-INFRA"),
        (ParamType.CATEGORICAL, "categorical"),
        (Verdict.INVALID, "INVALID"),
        (RunStatus.EVALUATING, "EVALUATING"),
        (CampaignStatus.ANALYZING, "ANALYZING"),
    ],
)
def test_enum_string_values_are_stable(member: str, value: str) -> None:
    assert member == value


def test_enum_member_sets_match_doc_05() -> None:
    assert [v.value for v in Verdict] == ["PASS", "FAIL", "INVALID"]
    assert len(FailureClass) == 9
    assert [s.value for s in RunStatus] == [
        "PENDING", "CLAIMED", "RUNNING", "EVALUATING", "DONE", "ERROR", "CANCELLED",
    ]  # fmt: skip
    assert [s.value for s in CampaignStatus] == [
        "CREATED", "RUNNING", "PAUSED", "ANALYZING", "COMPLETED", "FAILED", "CANCELLED",
    ]  # fmt: skip
    assert [s.value for s in NavStatus] == [0, 1, 2, 3, 4]


def test_phase_literal_matches_runs_phase_column() -> None:
    assert set(get_args(Phase)) == {
        "warmup", "falsify", "mode_search", "boundary", "refine",
        "explore", "baseline", "manual", "confirm", "replay",
    }  # fmt: skip


def test_package_exports_are_importable() -> None:
    for name in core_types.__all__:
        assert getattr(core_types, name) is not None


# --------------------------------------------------------------------------- models


def test_scenario_keeps_parameter_value_types() -> None:
    values = make_scenario().values
    assert isinstance(values["robot.max_speed"], float)
    assert isinstance(values["env.n_people"], int)
    assert isinstance(values["env.layout"], str)


@pytest.mark.parametrize(
    "model",
    [
        make_scenario(),
        make_oracle_result(),
        Pose2D(x=0, y=0, yaw=0),
        make_task(),
        SutProfile(id="k2d_default", backend="kinematic2d", config={"a": [1]}, config_hash="h"),
    ],
)
def test_models_are_immutable(model: Any) -> None:
    field = next(iter(type(model).model_fields))
    with pytest.raises(ValidationError, match="frozen"):
        setattr(model, field, None)


def test_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra"):
        make_scenario(unexpected=1)


def test_models_reject_non_finite_floats() -> None:
    with pytest.raises(ValidationError):
        Pose2D(x=math.nan, y=0, yaw=0)


def test_proposal_defaults_and_phase_validation() -> None:
    proposal = Proposal(scenario=make_scenario(), strategy="S-PROBE", phase="falsify")
    assert proposal.tags == ()
    assert proposal.acquisition_value is None
    with pytest.raises(ValidationError):
        Proposal(scenario=make_scenario(), strategy="S-PROBE", phase="not-a-phase")


@pytest.mark.parametrize("bad", [1.5, -1.01])
def test_oracle_result_robustness_bounded(bad: float) -> None:
    with pytest.raises(ValidationError, match="robustness"):
        make_oracle_result(robustness=bad)


def test_oracle_result_rejects_unknown_severity() -> None:
    with pytest.raises(ValidationError, match="severity"):
        make_oracle_result(severity="fatal")


@pytest.mark.parametrize(
    ("verdict", "robustness"),
    [(Verdict.INVALID, 0.1), (Verdict.PASS, None), (Verdict.FAIL, None)],
)
def test_observation_robustness_none_iff_invalid(
    verdict: Verdict, robustness: float | None
) -> None:
    with pytest.raises(ValidationError, match="if and only if"):
        Observation(
            x_unit=(0.5,), robustness=robustness, verdict=verdict, failure_class=None, run_id=RUN_ID
        )


def test_observation_valid_and_bounds() -> None:
    obs = Observation(
        x_unit=(0.0, 1.0), robustness=None, verdict=Verdict.INVALID,
        failure_class=FailureClass.INFRA, run_id=RUN_ID,
    )  # fmt: skip
    assert obs.failure_class is FailureClass.INFRA
    with pytest.raises(ValidationError):
        Observation(
            x_unit=(1.2,), robustness=0.0, verdict="PASS", failure_class=None, run_id=RUN_ID
        )
    with pytest.raises(ValidationError):
        Observation(
            x_unit=(0.2,), robustness=1.5, verdict="PASS", failure_class=None, run_id=RUN_ID
        )


def test_run_outcome_invariant_and_round_trip() -> None:
    outcome = RunOutcome(
        verdict=Verdict.FAIL, robustness=-0.2, primary_failure=FailureClass.COL,
        oracle_results=(make_oracle_result(),), metrics={"path_length": 12.0},
    )  # fmt: skip
    assert RunOutcome.model_validate_json(outcome.model_dump_json()) == outcome
    with pytest.raises(ValidationError, match="if and only if"):
        RunOutcome(
            verdict=Verdict.INVALID, robustness=0.0, primary_failure=None,
            oracle_results=(), metrics={},
        )  # fmt: skip


def test_task_spec_parses_doc_06_task_file_shape() -> None:
    task = make_task()
    assert task.start == Pose2D(x=2.12, y=-21.3, yaw=1.57)
    assert task.injected_obstacles[0].size == (0.8, 0.6, 0.15)
    assert task.injected_obstacles[0].placement.side == "left"
    assert task.time_limit.cap_s == 120


@pytest.mark.parametrize(
    "override",
    [
        {"goal_tolerance": {"xy": 0, "yaw": 0.5}},
        {"time_limit": {"factor": 2.5, "offset_s": -1, "cap_s": 120}},
        {"schema_version": 0},
        {"id": ""},
    ],
)
def test_task_spec_rejects_invalid_values(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_task(**override)


def test_scenario_and_proposal_are_hashable() -> None:
    assert hash(make_scenario()) == hash(make_scenario())
    assert len({make_scenario(), make_scenario(), make_scenario(scenario_hash="other")}) == 2
    proposal = Proposal(scenario=make_scenario(), strategy="S-RAND", phase="baseline")
    assert proposal in {proposal}


def test_value_objects_compare_by_value_and_pickle() -> None:
    assert make_scenario() == make_scenario()
    assert pickle.loads(pickle.dumps(make_task())) == make_task()  # noqa: S301


# --------------------------------------------------------------------------- trace


def test_trace_properties() -> None:
    trace = make_trace(5, meta={"rtf": 0.98})
    assert trace.n_samples == 5
    assert trace.duration_s == pytest.approx(0.4)
    assert trace.meta["rtf"] == 0.98
    assert isinstance(trace.goal_x, float)


def test_trace_empty_and_single_sample_have_zero_duration() -> None:
    assert make_trace(0).duration_s == 0.0
    assert make_trace(0).n_samples == 0
    assert make_trace(1).duration_s == 0.0


def test_trace_is_immutable() -> None:
    cols = trace_columns()
    trace = make_trace(**cols, meta={"k": 1})
    with pytest.raises(AttributeError):
        trace.goal_x = 3.0  # type: ignore[misc]
    with pytest.raises(ValueError, match="read-only"):
        trace.gt_x[0] = 1.0
    with pytest.raises(TypeError):
        trace.meta["k"] = 2  # type: ignore[index]
    cols["gt_x"][0] = 7.0  # caller's array stays writeable and is not copied
    assert trace.gt_x[0] == 7.0


def test_trace_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match=r"Trace\.gt_y has length 4, expected 5"):
        make_trace(gt_y=np.zeros(4))


@pytest.mark.parametrize(
    ("column", "bad", "match"),
    [
        ("gt_x", np.zeros(5, dtype=np.float32), "dtype float64"),
        ("contact", np.zeros(5, dtype=np.int8), "dtype bool"),
        ("nav_status", np.zeros(5, dtype=np.int64), "dtype int8"),
        ("roll", np.zeros((5, 1)), "1-D"),
        ("pitch", [0.0] * 5, "1-D"),
    ],
)
def test_trace_rejects_bad_columns(column: str, bad: Any, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        make_trace(**{column: bad})


@pytest.mark.parametrize(
    "t", [[0.0, 0.1, 0.1, 0.2, 0.3], [0.0, 0.2, 0.1, 0.3, 0.4], [0.0, 0.1, math.nan, 0.3, 0.4]]
)
def test_trace_requires_strictly_increasing_finite_time(t: list[float]) -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        make_trace(t=np.array(t, dtype=np.float64))


def test_trace_rejects_unknown_nav_status() -> None:
    with pytest.raises(ValueError, match="nav_status"):
        make_trace(nav_status=np.full(5, 9, dtype=np.int8))


def test_trace_rejects_non_finite_goal() -> None:
    with pytest.raises(ValueError, match="goal_y must be finite"):
        make_trace(goal_y=math.inf)


# --------------------------------------------------------------------------- properties

_unit = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
_rho = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False)


@st.composite
def observations(draw: st.DrawFn) -> Observation:
    verdict = draw(st.sampled_from(Verdict))
    return Observation(
        x_unit=tuple(draw(st.lists(_unit, max_size=8))),
        robustness=None if verdict is Verdict.INVALID else draw(_rho),
        verdict=verdict,
        failure_class=draw(st.none() | st.sampled_from(FailureClass)),
        run_id=draw(st.uuids()),
    )


@pytest.mark.property
@given(observations())
def test_observation_json_round_trip(obs: Observation) -> None:
    assert Observation.model_validate_json(obs.model_dump_json()) == obs
