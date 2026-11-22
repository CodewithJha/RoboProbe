"""Golden and property tests for :mod:`roboprobe.scenario.hashing` (FR-SCN-006).

The golden values are part of the reproducibility contract (docs/33 §6): a failing golden test
means stored scenario hashes no longer match. Never update them to make a test pass.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from roboprobe.core import errors
from roboprobe.scenario.hashing import canonical_json, content_hash, scenario_hash
from roboprobe.scenario.space import ScenarioSpace

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "spaces"

# (space_version, values, canonical bytes, scenario_hash)
GOLDEN = [
    (
        "4326a28381df",
        {"robot.max_speed": 0.26, "env.illuminance": 300.0, "obstacle.clearance": 0.8},
        b'{"space_version":"4326a28381df","values":{"env.illuminance":300.0,'
        b'"obstacle.clearance":0.8,"robot.max_speed":0.26}}',
        "4c576b5be442f310",
    ),
    (
        "4326a28381df",
        {"robot.max_speed": 0.5, "env.people": 3, "env.layout": "narrow"},
        b'{"space_version":"4326a28381df","values":{"env.layout":"narrow","env.people":3,'
        b'"robot.max_speed":0.5}}',
        "21ded8540940e4c0",
    ),
    (
        "fb5449ae0c1c",
        {"task.along": 0.1 + 0.2, "task.clearance": 1e-7, "robot.gain": -0.0},
        b'{"space_version":"fb5449ae0c1c","values":{"robot.gain":0.0,"task.along":0.3,'
        b'"task.clearance":1e-07}}',
        "405d6c87e91b3679",
    ),
    (
        "fb5449ae0c1c",
        {"a.x": 123456789012345.0, "a.y": 1e300, "a.z": -2.5e-12},
        b'{"space_version":"fb5449ae0c1c","values":{"a.x":123456789012000.0,"a.y":1e+300,'
        b'"a.z":-2.5e-12}}',
        "740c8a9976dc4107",
    ),
    ("abcdef012345", {}, b'{"space_version":"abcdef012345","values":{}}', "ba0be0799f3fe3aa"),
]


@pytest.mark.parametrize(("version", "values", "canonical", "expected"), GOLDEN)
def test_golden_scenario_hashes(
    version: str, values: dict[str, object], canonical: bytes, expected: str
) -> None:
    assert canonical_json({"space_version": version, "values": values}) == canonical
    assert hashlib.sha256(canonical).hexdigest()[:16] == expected
    assert scenario_hash(version, values) == expected


def test_canonical_rules() -> None:
    doc = {"b": [1, 2.0, True, None, "é"], "a": {"z": -0.0, "y": (1.23456789012345,)}}
    assert (
        canonical_json(doc)
        == '{"a":{"y":[1.23456789012],"z":0.0},"b":[1,2.0,true,null,"é"]}'.encode()
    )


def test_int_and_float_are_distinct_so_callers_normalise() -> None:
    assert canonical_json(1) != canonical_json(1.0)


def test_noise_below_twelve_significant_digits_is_absorbed() -> None:
    assert scenario_hash("v", {"p.x": 0.3}) == scenario_hash("v", {"p.x": 0.1 + 0.2})
    assert scenario_hash("v", {"p.x": 0.3}) != scenario_hash("v", {"p.x": 0.30000001})


@pytest.mark.parametrize(
    ("obj", "reason"),
    [
        ({"x": math.nan}, "non-finite"),
        ([math.inf], "non-finite"),
        ({"x": {1, 2}}, "unsupported type set"),
        ({"x": np.int64(3)}, "unsupported type int64"),
        ({1: "a", "1": "b"}, "collide"),
    ],
)
def test_unsupported_values_are_rejected(obj: object, reason: str) -> None:
    with pytest.raises(errors.ValidationError, match=reason):
        canonical_json(obj)


def test_content_hash_lengths() -> None:
    assert len(content_hash({"a": 1})) == 64
    assert content_hash({"a": 1}, length=12) == content_hash({"a": 1})[:12]


values_strategy = st.dictionaries(
    st.from_regex(r"[a-z]{1,6}\.[a-z_]{1,8}", fullmatch=True),
    st.floats(allow_nan=False, allow_infinity=False) | st.integers() | st.sampled_from(["a", "b"]),
    max_size=8,
)


@given(values_strategy, st.randoms(use_true_random=False))
def test_key_order_is_irrelevant(values: dict[str, object], rnd: object) -> None:
    items = list(values.items())
    rnd.shuffle(items)  # type: ignore[attr-defined]
    assert scenario_hash("v", dict(items)) == scenario_hash("v", values)


@given(values_strategy, st.data())
def test_any_value_change_changes_the_hash(values: dict[str, object], data: st.DataObject) -> None:
    key = data.draw(st.sampled_from(sorted(values))) if values else "p.new"
    changed = {**values, key: "changed-value"}
    assert scenario_hash("v", changed) != scenario_hash("v", values)
    assert scenario_hash("v2", values) != scenario_hash("v", values)


# --------------------------------------------------------------------------- make_scenario


def mixed() -> ScenarioSpace:
    return ScenarioSpace.from_yaml(FIXTURES / "valid" / "mixed.yaml", base_dir=FIXTURES)


def test_make_scenario_fills_nominals_normalises_types_and_hashes() -> None:
    space = mixed()
    scenario = space.make_scenario({"task.along": 0.5, "env.people": 2.0, "robot.gain": 1})
    assert scenario.space_id == "mixed_v1"
    assert scenario.space_version == space.version
    assert scenario.values == {
        "task.along": 0.5,
        "task.clearance": 0.5,
        "env.people": 2,
        "env.layout": "wide",
        "env.lux": 300.0,
        "robot.gain": 1.0,
    }
    assert type(scenario.values["env.people"]) is int
    assert type(scenario.values["robot.gain"]) is float
    assert scenario.scenario_hash == scenario_hash(space.version, scenario.values)


def test_equal_points_hash_equally_whatever_the_input_types_or_order() -> None:
    space = mixed()
    a = space.make_scenario({"robot.gain": 1, "env.people": 2})
    b = space.make_scenario({"env.people": 2.0, "robot.gain": 1.0})
    assert a.scenario_hash == b.scenario_hash
    assert a == b


def test_nominal_scenario() -> None:
    space = mixed()
    assert space.nominal().values == {
        spec.id: space.make_scenario({}).values[spec.id] for spec in space.parameters
    }


@pytest.mark.parametrize(
    ("values", "match"),
    [
        ({"robot.nope": 1.0}, "unknown parameter"),
        ({"env.lux": 10.0}, "disabled parameter"),
        ({"task.along": 0.9}, "outside"),
        ({"env.people": 1.5}, "not an integer"),
        ({"env.layout": "round"}, "not one of"),
        ({"env.people": 3, "task.clearance": 0.1}, "violates constraint"),
    ],
)
def test_make_scenario_rejects_invalid_points(values: dict[str, object], match: str) -> None:
    with pytest.raises(errors.ValidationError, match=match):
        mixed().make_scenario(values)


def test_disabled_parameter_may_be_passed_at_its_nominal_value() -> None:
    assert mixed().make_scenario({"env.lux": 300}).values["env.lux"] == 300.0
