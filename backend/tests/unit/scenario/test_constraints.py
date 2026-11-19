"""Unit tests for :mod:`roboprobe.scenario.constraints` (FR-SCN-004, NFR-SEC-003)."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pytest

from roboprobe.core import errors
from roboprobe.core.settings import ScenarioSettings
from roboprobe.scenario.constraints import (
    ConstraintSet,
    compile_constraint,
    rejection_sample,
)

pytestmark = pytest.mark.unit

COLUMNS = ("robot.speed", "comms.delay")
ACCEPTANCE_SAMPLES = 10_000
LIMIT = 0.1


class UnitCubeSampler:
    """Minimal uniform sampler over ``[0, 1]^d`` (stands in for the scenario samplers)."""

    def __init__(self, dim: int) -> None:
        """Sample ``dim``-dimensional points and count calls."""
        self.dim = dim
        self.calls = 0

    def sample(self, n: int, rng: np.random.Generator) -> npt.NDArray[np.float64]:
        self.calls += 1
        return rng.random((n, self.dim))


# --------------------------------------------------------------------------- grammar


@pytest.mark.parametrize(
    ("expr", "values", "expected"),
    [
        ("robot.speed * comms.delay <= 0.1", {"robot.speed": 0.5, "comms.delay": 0.1}, True),
        ("robot.speed * comms.delay <= 0.1", {"robot.speed": 0.5, "comms.delay": 0.3}, False),
        ("0 < robot.speed < 1", {"robot.speed": 0.5}, True),
        ("0 < robot.speed < 1", {"robot.speed": 1.5}, False),
        (
            "not robot.speed > 1 and (comms.delay >= 2 or comms.delay == 0)",
            {"robot.speed": 0.5, "comms.delay": 0},
            True,
        ),
        ("abs(-robot.speed) + +1 != 2", {"robot.speed": 1}, False),
        (
            "min(robot.speed, 2, comms.delay) - max(1, robot.speed) ** 2 / 4 < 0",
            {"robot.speed": 3, "comms.delay": 5},
            True,
        ),
    ],
)
def test_allowed_expressions_evaluate(expr: str, values: dict[str, float], expected: bool) -> None:
    assert bool(compile_constraint(expr).evaluate(values)) is expected


def test_referenced_ids_are_collected() -> None:
    compiled = compile_constraint("robot.speed * comms.delay <= 150 or abs(env.lux) > 1")
    assert compiled.param_ids == {"robot.speed", "comms.delay", "env.lux"}


@pytest.mark.parametrize(
    ("expr", "reason"),
    [
        ("__import__('os').system('true') == 0", "only calls to"),
        ("().__class__ == 1", "Attribute access is only allowed|attribute access"),
        ("open('/etc/passwd') == 1", "only calls to"),
        ("(lambda: 1)() == 1", "only calls to"),
        ("(lambda: 1) == 1", "Lambda is not allowed"),
        ("robot.__class__ == 1", "names starting with '_'"),
        ("Robot.speed < 1", "not a valid parameter id"),
        ("robot.speed.real < 1", "attribute access"),
        ("robot.speed[0] < 1", "Subscript is not allowed"),
        ("robot < 1", "Name is not allowed"),
        ("robot.speed < 'fast'", "only numeric literals"),
        ("robot.speed < True", "only numeric literals"),
        ("robot.speed < 1j", "only numeric literals"),
        ("robot.speed % 2 == 0", "operator Mod"),
        ("~robot.speed < 1", "operator Invert"),
        ("robot.speed in (1, 2)", "comparison In"),
        ("robot.speed is 1", "comparison Is"),
        ("robot.speed + 1", "expected a comparison"),
        ("(robot.speed < 1) + 1 > 0", "expected a number"),
        ("abs(robot.speed, 1) < 1", "wrong number of arguments"),
        ("min(robot.speed) < 1", "wrong number of arguments"),
        ("max(*robot.speed) < 1", "positional arguments only"),
        ("abs(x=robot.speed) < 1", "positional arguments only"),
        ("robot.speed <", "invalid expression"),
        ("robot.speed < 1\x00", "invalid expression"),
        ("1 if robot.speed else 0 < 1", "IfExp is not allowed"),
    ],
)
def test_disallowed_expressions_are_rejected_at_compile_time(expr: str, reason: str) -> None:
    with pytest.raises(errors.ValidationError, match=reason) as exc:
        compile_constraint(expr)
    assert exc.value.context["expr"] == expr


@pytest.mark.parametrize(
    "expr",
    [
        "-" * 100_000 + "robot.speed < 1",  # beyond the parser's limits
        "-" * 500 + "robot.speed < 1",  # parses, but too deep for the compiler
        "1 + " * 3000 + "robot.speed < 1",
    ],
)
def test_deeply_nested_expression_is_a_validation_error(expr: str) -> None:
    with pytest.raises(errors.ValidationError, match="invalid constraint"):
        compile_constraint(expr)


def test_float_edge_cases_never_raise_and_nan_is_infeasible() -> None:
    compiled = compile_constraint("robot.speed / comms.delay < 1")
    assert not compiled.evaluate({"robot.speed": 0.0, "comms.delay": 0.0})  # nan
    assert not compiled.evaluate({"robot.speed": 1.0, "comms.delay": 0.0})  # inf
    assert bool(compile_constraint("10 ** robot.speed > 1").evaluate({"robot.speed": 1e6}))


def test_missing_and_non_numeric_values_are_validation_errors() -> None:
    compiled = compile_constraint("robot.speed < 1")
    with pytest.raises(errors.ValidationError, match="needs a value"):
        compiled.evaluate({})
    with pytest.raises(errors.ValidationError, match="not numeric"):
        compiled.evaluate({"robot.speed": "fast"})
    with pytest.raises(errors.ValidationError, match="1-D"):
        compiled.evaluate({"robot.speed": [[1.0]]})


# --------------------------------------------------------------------------- vectorisation


def test_batch_evaluation_matches_pointwise() -> None:
    rng = np.random.default_rng(7)
    batch = rng.random((50, 2))
    compiled = compile_constraint("robot.speed * comms.delay <= 0.1")
    mask = compiled.evaluate_batch(batch, COLUMNS)
    pointwise = [bool(compiled.evaluate(dict(zip(COLUMNS, row, strict=True)))) for row in batch]
    assert mask.shape == (50,)
    assert mask.tolist() == pointwise


def test_constant_constraint_broadcasts_to_the_batch() -> None:
    mask = compile_constraint("1 < 2").evaluate_batch(np.zeros((3, 2)), COLUMNS)
    assert mask.tolist() == [True, True, True]


def test_batch_shape_is_checked() -> None:
    with pytest.raises(errors.ValidationError, match=r"\(n, 2\) batch"):
        compile_constraint("1 < 2").evaluate_batch(np.zeros(3), COLUMNS)


def test_constraint_set_is_a_conjunction() -> None:
    constraints = ConstraintSet.compile(["robot.speed < 0.5", "comms.delay > 0.5"])
    batch = np.array([[0.1, 0.9], [0.9, 0.9], [0.1, 0.1]])
    assert constraints.mask(batch, COLUMNS).tolist() == [True, False, False]
    assert constraints.param_ids == set(COLUMNS)
    assert constraints.is_satisfied({"robot.speed": 0.1, "comms.delay": 0.9})
    assert not constraints.is_satisfied({"robot.speed": 0.9, "comms.delay": 0.9})


def test_empty_constraint_set_accepts_everything() -> None:
    empty = ConstraintSet()
    assert empty.is_satisfied({})
    assert empty.mask(np.zeros((2, 2)), COLUMNS).tolist() == [True, True]
    assert empty.param_ids == frozenset()


# --------------------------------------------------------------------------- rejection sampling


def product_feasibility(batch: npt.NDArray[np.float64]) -> npt.NDArray[np.bool_]:
    return ConstraintSet.compile([f"robot.speed * comms.delay <= {LIMIT}"]).mask(batch, COLUMNS)


def test_rejection_sampling_never_yields_a_violating_point() -> None:
    points = rejection_sample(
        UnitCubeSampler(2),
        product_feasibility,
        ACCEPTANCE_SAMPLES,
        np.random.default_rng(42),
        max_attempts=ScenarioSettings().constraint_max_attempts,
    )
    assert points.shape == (ACCEPTANCE_SAMPLES, 2)
    assert np.all(points[:, 0] * points[:, 1] <= LIMIT)


def test_rejection_sampling_is_deterministic_for_a_seed() -> None:
    def draw() -> npt.NDArray[np.float64]:
        return rejection_sample(
            UnitCubeSampler(2), product_feasibility, 100, np.random.default_rng(3), max_attempts=50
        )

    np.testing.assert_array_equal(draw(), draw())


def test_rejection_sampling_gives_up_after_max_attempts() -> None:
    sampler = UnitCubeSampler(2)
    never = ConstraintSet.compile(["robot.speed > 2"])
    with pytest.raises(errors.ValidationError, match="after 5 sampling attempts") as exc:
        rejection_sample(
            sampler,
            lambda b: never.mask(b, COLUMNS),
            10,
            np.random.default_rng(0),
            max_attempts=5,
        )
    assert sampler.calls == 5
    assert exc.value.context == {"found": 0, "wanted": 10, "max_attempts": 5}


@pytest.mark.parametrize(("n", "attempts"), [(0, 1), (1, 0)])
def test_rejection_sampling_rejects_non_positive_arguments(n: int, attempts: int) -> None:
    with pytest.raises(errors.ValidationError, match="n >= 1"):
        rejection_sample(
            UnitCubeSampler(2),
            product_feasibility,
            n,
            np.random.default_rng(0),
            max_attempts=attempts,
        )


def test_max_attempts_setting_is_validated() -> None:
    assert ScenarioSettings().constraint_max_attempts == 1000
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        ScenarioSettings(constraint_max_attempts=0)
