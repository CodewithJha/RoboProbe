"""Unit tests for unit-hypercube normalisation (T-021; docs/06 §4.1, FR-SCN-003)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from structlog.testing import capture_logs

from roboprobe.core import errors
from roboprobe.core.types import ParamType
from roboprobe.scenario import normalize
from roboprobe.scenario.space import ParameterSpec, PriorSpec, ScenarioSpace

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
WAREHOUSE = REPO_ROOT / "configs" / "scenario_spaces" / "warehouse_v1.yaml"
UNIFORM = PriorSpec(kind="uniform")

LUX = ParameterSpec(
    id="env.illuminance", name="Lux", type=ParamType.FLOAT, unit="lux", low=5, high=1000,
    nominal=300, scale="log", prior=PriorSpec(kind="loguniform"), group="environment",
)  # fmt: skip
SPEED = ParameterSpec(
    id="robot.max_speed", name="Speed", type=ParamType.FLOAT, unit="m/s", low=0.1, high=0.5,
    nominal=0.26, prior=UNIFORM, group="robot",
)  # fmt: skip
DELAY = ParameterSpec(
    id="comms.cmd_delay_ms", name="Delay", type=ParamType.INT, unit="ms", low=0, high=4,
    nominal=0, prior=UNIFORM, group="comms",
)  # fmt: skip
FLOOR = ParameterSpec(
    id="env.floor", name="Floor", type=ParamType.CATEGORICAL, unit="-",
    choices=("dry", "wet", "oily"), nominal="dry", prior=UNIFORM, group="environment",
)  # fmt: skip
PARAMS = (LUX, SPEED, DELAY, FLOOR)
NOMINAL = {
    "env.illuminance": 300.0,
    "robot.max_speed": 0.26,
    "comms.cmd_delay_ms": 0,
    "env.floor": "dry",
}


def issue_paths(exc: pytest.ExceptionInfo[errors.ValidationError]) -> list[str]:
    return [issue["path"] for issue in exc.value.context["errors"]]  # type: ignore[index, union-attr]


def test_log_scale_midpoint_is_geometric_mean() -> None:
    assert normalize.from_unit([LUX], [0.5])["env.illuminance"] == pytest.approx(
        math.sqrt(5 * 1000)
    )
    assert normalize.to_unit([LUX], {"env.illuminance": math.sqrt(5000)})[0] == pytest.approx(0.5)


def test_linear_endpoints_and_midpoint() -> None:
    assert normalize.to_unit([SPEED], {"robot.max_speed": 0.1})[0] == 0.0
    assert normalize.to_unit([SPEED], {"robot.max_speed": 0.5})[0] == 1.0
    assert normalize.from_unit([SPEED], [0.5])["robot.max_speed"] == pytest.approx(0.3)


@pytest.mark.parametrize(("value", "expected"), [(0, 0.1), (2, 0.5), (4, 0.9)])
def test_int_maps_to_bin_centre(value: int, expected: float) -> None:
    assert normalize.to_unit([DELAY], {"comms.cmd_delay_ms": value})[0] == pytest.approx(expected)


@pytest.mark.parametrize(("u", "expected"), [(0.0, 0), (0.199, 0), (0.2, 1), (0.99, 4), (1.0, 4)])
def test_int_inverse_uses_bins_and_clips_the_top_edge(u: float, expected: int) -> None:
    value = normalize.from_unit([DELAY], [u])["comms.cmd_delay_ms"]
    assert value == expected
    assert type(value) is int


@pytest.mark.parametrize(
    ("u", "expected"),
    [(0.0, "dry"), (1 / 3 - 1e-9, "dry"), (1 / 3, "wet"), (0.7, "oily"), (1.0, "oily")],
)
def test_categorical_bins(u: float, expected: str) -> None:
    assert normalize.from_unit([FLOOR], [u])["env.floor"] == expected


def test_categorical_maps_to_bin_centre() -> None:
    assert normalize.to_unit([FLOOR], {"env.floor": "wet"})[0] == pytest.approx(0.5)


def test_round_trip_of_mixed_vector() -> None:
    u = normalize.to_unit(PARAMS, NOMINAL)
    assert u.shape == (4,)
    assert u.dtype == np.float64
    back = normalize.from_unit(PARAMS, u)
    assert back["comms.cmd_delay_ms"] == 0
    assert back["env.floor"] == "dry"
    assert back["env.illuminance"] == pytest.approx(300.0, abs=1e-9)
    assert back["robot.max_speed"] == pytest.approx(0.26, abs=1e-9)


def test_batch_shapes_and_row_order() -> None:
    other = {**NOMINAL, "comms.cmd_delay_ms": 3, "env.floor": "oily"}
    matrix = normalize.to_unit_batch(PARAMS, [NOMINAL, other])
    assert matrix.shape == (2, 4)
    rows = normalize.from_unit_batch(PARAMS, matrix)
    assert [r["comms.cmd_delay_ms"] for r in rows] == [0, 3]
    assert [r["env.floor"] for r in rows] == ["dry", "oily"]


def test_empty_parameter_list() -> None:
    assert normalize.to_unit((), {}).shape == (0,)
    assert normalize.from_unit_batch((), np.empty((2, 0))) == [{}, {}]


def test_integral_floats_and_numpy_scalars_are_accepted() -> None:
    values = {**NOMINAL, "comms.cmd_delay_ms": 2.0, "robot.max_speed": np.float32(0.25)}
    assert normalize.to_unit(PARAMS, values)[2] == pytest.approx(0.5)
    assert normalize.to_unit([DELAY], {"comms.cmd_delay_ms": np.int64(4)})[0] == pytest.approx(0.9)


def test_extra_keys_are_ignored() -> None:
    normalize.to_unit([SPEED], {"robot.max_speed": 0.2, "unrelated": object()})


@pytest.mark.parametrize(
    ("param", "value", "message"),
    [
        (SPEED, 0.6, "outside"),
        (SPEED, 0.05, "outside"),
        (SPEED, float("nan"), "finite"),
        (SPEED, "fast", "expected a number"),
        (SPEED, True, "expected a number"),
        (DELAY, 1.5, "not an integer"),
        (FLOOR, "icy", "not one of"),
        (FLOOR, 1, "not one of"),
    ],
)
def test_invalid_values_are_rejected(param: ParameterSpec, value: object, message: str) -> None:
    with pytest.raises(errors.ValidationError, match=message) as exc:
        normalize.to_unit([param], {param.id: value})
    assert issue_paths(exc) == [f"/{param.id}"]


def test_every_problem_is_reported_with_row_pointers() -> None:
    rows = [NOMINAL, {"robot.max_speed": 9.0, "env.floor": "icy"}]
    with pytest.raises(errors.ValidationError) as exc:
        normalize.to_unit_batch(PARAMS, rows)
    assert issue_paths(exc) == [
        "/1/env.illuminance",
        "/1/robot.max_speed",
        "/1/comms.cmd_delay_ms",
        "/1/env.floor",
    ]


@pytest.mark.parametrize("u", [[0.5], [[0.5, 0.5, 0.5, 0.5]], [0.5] * 5])
def test_from_unit_rejects_wrong_shape(u: object) -> None:
    with pytest.raises(errors.ValidationError, match="expected shape"):
        normalize.from_unit(PARAMS, u)  # type: ignore[arg-type]


def test_from_unit_batch_rejects_wrong_shape() -> None:
    with pytest.raises(errors.ValidationError, match="expected shape"):
        normalize.from_unit_batch(PARAMS, np.zeros((2, 3)))


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_from_unit_rejects_non_finite(bad: float) -> None:
    with pytest.raises(errors.ValidationError, match="finite"):
        normalize.from_unit([SPEED], [bad])


def test_out_of_range_unit_is_clipped_with_warning() -> None:
    with capture_logs() as logs:
        low = normalize.from_unit([SPEED, DELAY], [-0.2, 1.3])
    assert low == {"robot.max_speed": pytest.approx(0.1), "comms.cmd_delay_ms": 4}
    assert [entry["event"] for entry in logs] == ["scenario.unit_clipped"]
    assert logs[0]["log_level"] == "warning"
    assert logs[0]["count"] == 2


def test_in_range_unit_does_not_warn() -> None:
    with capture_logs() as logs:
        normalize.from_unit([SPEED], [1.0])
    assert logs == []


def test_decoded_floats_stay_within_bounds() -> None:
    values = normalize.from_unit_batch([LUX, SPEED], np.array([[0.0, 0.0], [1.0, 1.0]]))
    assert values[0] == {"env.illuminance": 5.0, "robot.max_speed": 0.1}
    assert values[1]["env.illuminance"] <= 1000.0
    assert values[1]["robot.max_speed"] <= 0.5


def test_space_methods_delegate_over_enabled_parameters() -> None:
    space = ScenarioSpace.from_yaml(WAREHOUSE, base_dir=REPO_ROOT)
    nominal = space.nominal_values()
    u = space.to_unit(nominal)
    assert u.shape == (space.dim,)
    back = space.from_unit(u)
    assert set(back) == {p.id for p in space.params}
    for spec in space.params:
        assert back[spec.id] == pytest.approx(nominal[spec.id], abs=1e-9)
    assert space.to_unit_batch([nominal, nominal]).shape == (2, space.dim)
    assert len(space.from_unit_batch(np.full((3, space.dim), 0.5))) == 3
