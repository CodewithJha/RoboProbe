"""Fuzz tests: the constraint compiler only ever fails with ``ValidationError`` (NFR-SEC-003)."""

from __future__ import annotations

import contextlib
import math

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from roboprobe.core import errors
from roboprobe.scenario.constraints import compile_constraint

pytestmark = pytest.mark.property

PARAMS = ("robot.speed", "comms.delay", "env.lux")
TOKENS = (
    *PARAMS, "0", "1", "2.5", "1e308", "-", "+", "*", "/", "**", "%", "<", "<=", ">", ">=", "==",
    "!=", "and", "or", "not", "(", ")", ",", "abs", "min", "max", "[", "]", ".", "__class__",
    "lambda", ":", "'s'", "True", "open", "__import__", "if", "else", "in", "is", "~", "@",
)  # fmt: skip

numbers = st.sampled_from(PARAMS) | st.floats(allow_nan=False, allow_infinity=False).map(repr)
numeric_exprs = st.recursive(
    numbers,
    lambda inner: st.one_of(
        st.tuples(inner, st.sampled_from(["+", "-", "*", "/", "**"]), inner).map(
            lambda t: f"({t[0]} {t[1]} {t[2]})"
        ),
        inner.map(lambda e: f"abs(-{e})"),
        st.lists(inner, min_size=2, max_size=3).map(lambda xs: f"min({', '.join(xs)})"),
        st.lists(inner, min_size=2, max_size=3).map(lambda xs: f"max({', '.join(xs)})"),
    ),
    max_leaves=12,
)
comparisons = st.tuples(
    numeric_exprs, st.sampled_from(["<", "<=", ">", ">=", "==", "!="]), numeric_exprs
).map(lambda t: f"{t[0]} {t[1]} {t[2]}")
boolean_exprs = st.recursive(
    comparisons,
    lambda inner: st.one_of(
        st.tuples(inner, st.sampled_from(["and", "or"]), inner).map(
            lambda t: f"({t[0]} {t[1]} {t[2]})"
        ),
        inner.map(lambda e: f"not ({e})"),
    ),
    max_leaves=6,
)
values = st.fixed_dictionaries(
    {p: st.floats(allow_nan=True, allow_infinity=True) | st.integers() for p in PARAMS}
)


@given(st.lists(st.sampled_from(TOKENS), max_size=25).map(" ".join))
def test_token_soup_only_raises_validation_error(expr: str) -> None:
    with contextlib.suppress(errors.ValidationError):
        compile_constraint(expr)


@given(st.text(max_size=60))
def test_arbitrary_text_only_raises_validation_error(expr: str) -> None:
    with contextlib.suppress(errors.ValidationError):
        compile_constraint(expr)


@given(boolean_exprs, values)
def test_well_formed_expressions_compile_and_evaluate_to_a_bool(
    expr: str, point: dict[str, float]
) -> None:
    compiled = compile_constraint(expr)
    assert compiled.param_ids <= set(PARAMS)
    assert isinstance(bool(compiled.evaluate(point)), bool)


@given(numeric_exprs, numeric_exprs, values)
def test_batch_and_pointwise_evaluation_agree(
    left: str, right: str, point: dict[str, float]
) -> None:
    compiled = compile_constraint(f"{left} <= {right}")
    finite = {k: v if math.isfinite(v) else 0.0 for k, v in point.items()}
    batch = np.array([[finite[p] for p in PARAMS]] * 2, dtype=np.float64)
    mask = compiled.evaluate_batch(batch, PARAMS)
    assert mask.tolist() == [bool(compiled.evaluate(finite))] * 2
