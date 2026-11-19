"""Tests for pinned parameters and sub-spaces (T-025; FR-SCN-007, docs/05 §3)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from roboprobe.core import errors
from roboprobe.core.types import ParamType
from roboprobe.scenario.space import ParameterSpec, PriorSpec, ScenarioSpace

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
WAREHOUSE = REPO_ROOT / "configs" / "scenario_spaces" / "warehouse_v1.yaml"
N_SCENARIOS = 10_000
PINS = {"env.illuminance": 12.5, "comms.cmd_delay_ms": 140}


@pytest.fixture(scope="module")
def space() -> ScenarioSpace:
    return ScenarioSpace.from_yaml(WAREHOUSE, base_dir=REPO_ROOT)


def issue_paths(exc: pytest.ExceptionInfo[errors.ValidationError]) -> list[str]:
    return [issue["path"] for issue in exc.value.context["errors"]]  # type: ignore[index, union-attr]


def test_pins_remove_dimensions_but_keep_identity(space: ScenarioSpace) -> None:
    pinned = space.with_pins(PINS)
    assert pinned.dim == space.dim - len(PINS)
    assert {p.id for p in pinned.params}.isdisjoint(PINS)
    assert (pinned.id, pinned.version) == (space.id, space.version)
    assert dict(pinned.pins) == {"env.illuminance": 12.5, "comms.cmd_delay_ms": 140.0}
    assert space.pins == {}
    assert space.dim == 6


def test_pinned_values_never_vary_across_sampled_scenarios(space: ScenarioSpace) -> None:
    pinned = space.with_pins(PINS)
    u = np.random.default_rng(0).random((N_SCENARIOS, pinned.dim))
    scenarios = [pinned.make_scenario(row) for row in pinned.from_unit_batch(u)]
    rows = [s.values for s in scenarios]
    assert len(rows) == N_SCENARIOS
    for key, value in PINS.items():
        assert {row[key] for row in rows} == {value}
    assert len({row["robot.max_speed"] for row in rows}) > N_SCENARIOS // 2  # free ones still vary
    assert all(
        row["obstacle.along_path"] == space.param("obstacle.along_path").nominal for row in rows
    )


def test_unit_round_trip_operates_on_free_dimensions(space: ScenarioSpace) -> None:
    pinned = space.with_pins(PINS)
    values = pinned.nominal_values()
    u = pinned.to_unit(values)
    assert u.shape == (pinned.dim,)
    back = pinned.from_unit(u)
    assert set(back) == {p.id for p in pinned.params}
    full = pinned.make_scenario(back).values
    assert set(full) == {p.id for p in space.parameters}
    assert full["env.illuminance"] == 12.5


def test_nominal_values_apply_pins(space: ScenarioSpace) -> None:
    nominal = space.with_pins(PINS).nominal_values()
    assert nominal["env.illuminance"] == 12.5
    assert nominal["robot.max_speed"] == space.param("robot.max_speed").nominal


def test_pins_accumulate_and_can_be_overridden(space: ScenarioSpace) -> None:
    pinned = space.with_pins({"env.illuminance": 12.5}).with_pins({"robot.max_speed": 0.3})
    assert list(pinned.pins) == ["robot.max_speed", "env.illuminance"]  # file order
    assert pinned.with_pins({"env.illuminance": 50}).pins["env.illuminance"] == 50.0
    assert pinned.dim == space.dim - 2


def test_disabled_parameters_can_be_pinned(space: ScenarioSpace) -> None:
    pinned = space.with_pins({"sensor.lidar_dropout": 0.1})
    assert pinned.dim == space.dim
    assert pinned.nominal_values()["sensor.lidar_dropout"] == 0.1


def test_invalid_pins_are_all_reported(space: ScenarioSpace) -> None:
    bad = {"env.illuminance": 2000, "robot.nope": 1, "comms.cmd_delay_ms": "slow"}
    with pytest.raises(errors.ValidationError) as exc:
        space.with_pins(bad)
    assert sorted(issue_paths(exc)) == [
        "/pins/comms.cmd_delay_ms",
        "/pins/env.illuminance",
        "/pins/robot.nope",
    ]
    assert "outside" in str(exc.value)


def test_pinning_every_enabled_parameter_is_rejected(space: ScenarioSpace) -> None:
    everything = {p.id: p.nominal for p in space.params}
    with pytest.raises(errors.ValidationError, match="must stay free") as exc:
        space.with_pins(everything)
    assert issue_paths(exc) == ["/pins"]


def test_values_are_coerced_to_parameter_type() -> None:
    count = ParameterSpec(
        id="env.people", name="People", type=ParamType.INT, unit="count", low=0, high=5, nominal=0,
        prior=PriorSpec(kind="uniform"), group="environment",
    )  # fmt: skip
    floor = ParameterSpec(
        id="env.floor", name="Floor", type=ParamType.CATEGORICAL, unit="-", choices=("dry", "wet"),
        nominal="dry", prior=PriorSpec(kind="uniform"), group="environment",
    )  # fmt: skip
    space = ScenarioSpace.from_yaml(WAREHOUSE, base_dir=REPO_ROOT)
    custom = space.model_copy(update={"parameters": (*space.parameters, count, floor)})
    pinned = custom.with_pins({"env.people": 3.0, "env.floor": "wet"})
    assert pinned.pins["env.people"] == 3
    assert type(pinned.pins["env.people"]) is int
    assert pinned.pins["env.floor"] == "wet"


def test_make_scenario_rejects_other_values_for_pins(space: ScenarioSpace) -> None:
    pinned = space.with_pins(PINS)
    assert pinned.make_scenario({"env.illuminance": 12.5}).values["env.illuminance"] == 12.5
    with pytest.raises(errors.ValidationError, match=r"pinned to 12\.5") as exc:
        pinned.make_scenario({"env.illuminance": 13.0, "robot.ghost": 1.0})
    assert sorted(issue_paths(exc)) == ["/env.illuminance", "/robot.ghost"]


def test_hash_includes_pinned_values(space: ScenarioSpace) -> None:
    a = space.with_pins({"env.illuminance": 12.5}).nominal()
    b = space.with_pins({"env.illuminance": 50.0}).nominal()
    assert a.scenario_hash != b.scenario_hash
    assert a.scenario_hash == space.make_scenario({"env.illuminance": 12.5}).scenario_hash
    assert a.space_version == space.version


def test_pinned_disabled_parameter_reaches_the_scenario(space: ScenarioSpace) -> None:
    pinned = space.with_pins({"sensor.lidar_dropout": 0.1})
    assert pinned.nominal().values["sensor.lidar_dropout"] == 0.1
    assert pinned.make_scenario({"sensor.lidar_dropout": 0.1}).values["sensor.lidar_dropout"] == 0.1


def test_pins_are_immutable_and_serialise(space: ScenarioSpace) -> None:
    pinned = space.with_pins(PINS)
    with pytest.raises(TypeError):
        pinned.pins["robot.max_speed"] = 0.2  # type: ignore[index]
    dumped = pinned.model_dump(mode="json")
    assert dumped["pins"] == {"env.illuminance": 12.5, "comms.cmd_delay_ms": 140.0}
    restored = ScenarioSpace.model_validate(dumped)
    assert restored.pins == pinned.pins
    assert restored.dim == pinned.dim
