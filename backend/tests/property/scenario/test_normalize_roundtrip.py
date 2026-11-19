"""Property tests: unit-hypercube round-trips (T-021; FR-SCN-003, docs/18 §4.1).

Floats round-trip within 1e-9 (relative to the range width when it exceeds 1). Ints and categoricals
round-trip exactly. Any ``u`` in ``[0, 1]`` decodes inside the bounds and re-encodes into the same
bin. Each property runs ``ROUNDTRIP_EXAMPLES`` examples, which is the issue's acceptance budget.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from roboprobe.core.types import ParamType
from roboprobe.scenario import normalize
from roboprobe.scenario.space import ParameterSpec, PriorSpec

pytestmark = pytest.mark.property

ROUNDTRIP_EXAMPLES = 10_000
FLOAT_TOLERANCE = 1e-9
MAGNITUDE = 1e4
MIN_WIDTH = 1e-3
MAX_CHOICES = 12
UNIFORM = PriorSpec(kind="uniform")

roundtrip = settings(max_examples=ROUNDTRIP_EXAMPLES, deadline=None)
finite = st.floats(-MAGNITUDE, MAGNITUDE, allow_nan=False, allow_infinity=False)
unit = st.floats(0.0, 1.0)


@st.composite
def float_param_and_value(draw: st.DrawFn) -> tuple[ParameterSpec, float]:
    log = draw(st.booleans())
    if log:
        low = draw(st.floats(MIN_WIDTH, MAGNITUDE / 2))
        high = draw(st.floats(low * (1 + MIN_WIDTH), MAGNITUDE))
    else:
        low = draw(finite.filter(lambda x: x < MAGNITUDE - 1))
        high = draw(st.floats(low + MIN_WIDTH, MAGNITUDE))
    value = draw(st.floats(low, high))
    spec = ParameterSpec(
        id="robot.x", name="x", type=ParamType.FLOAT, unit="-", low=low, high=high, nominal=low,
        scale="log" if log else "linear",
        prior=PriorSpec(kind="loguniform") if log else UNIFORM, group="robot",
    )  # fmt: skip
    return spec, value


@st.composite
def int_param_and_value(draw: st.DrawFn) -> tuple[ParameterSpec, int]:
    low = draw(st.integers(-10_000, 10_000))
    high = draw(st.integers(low + 1, low + 10_000))
    spec = ParameterSpec(
        id="comms.n", name="n", type=ParamType.INT, unit="-", low=low, high=high, nominal=low,
        prior=UNIFORM, group="comms",
    )  # fmt: skip
    return spec, draw(st.integers(low, high))


@st.composite
def categorical_param_and_value(draw: st.DrawFn) -> tuple[ParameterSpec, str]:
    k = draw(st.integers(2, MAX_CHOICES))
    choices = tuple(f"c{i}" for i in range(k))
    spec = ParameterSpec(
        id="env.c", name="c", type=ParamType.CATEGORICAL, unit="-", choices=choices,
        nominal=choices[0], prior=UNIFORM, group="environment",
    )  # fmt: skip
    return spec, draw(st.sampled_from(choices))


@roundtrip
@given(float_param_and_value())
def test_float_round_trip(case: tuple[ParameterSpec, float]) -> None:
    spec, value = case
    u = normalize.to_unit([spec], {spec.id: value})
    assert 0.0 <= u[0] <= 1.0
    back = normalize.from_unit([spec], u)[spec.id]
    assert isinstance(back, float)
    width = (spec.high or 0.0) - (spec.low or 0.0)
    assert abs(back - value) < FLOAT_TOLERANCE * max(1.0, width)


@roundtrip
@given(int_param_and_value())
def test_int_round_trip_is_exact(case: tuple[ParameterSpec, int]) -> None:
    spec, value = case
    assert (
        normalize.from_unit([spec], normalize.to_unit([spec], {spec.id: value}))[spec.id] == value
    )


@roundtrip
@given(categorical_param_and_value())
def test_categorical_round_trip_is_exact(case: tuple[ParameterSpec, str]) -> None:
    spec, value = case
    assert (
        normalize.from_unit([spec], normalize.to_unit([spec], {spec.id: value}))[spec.id] == value
    )


@roundtrip
@given(st.one_of(int_param_and_value(), categorical_param_and_value()), unit)
def test_discrete_decode_is_a_projection(case: tuple[ParameterSpec, object], u: float) -> None:
    spec, _ = case
    decoded = normalize.from_unit([spec], [u])
    again = normalize.from_unit([spec], normalize.to_unit([spec], decoded))
    assert again == decoded


@roundtrip
@given(float_param_and_value(), unit)
def test_decoded_float_stays_in_bounds(case: tuple[ParameterSpec, float], u: float) -> None:
    spec, _ = case
    value = normalize.from_unit([spec], [u])[spec.id]
    assert isinstance(value, float)
    assert math.isfinite(value)
    assert (spec.low or 0.0) <= value <= (spec.high or 0.0)
