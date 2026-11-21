"""TM-03: constraint expressions cannot escape the whitelist (T-022, T-109)."""

from __future__ import annotations

import pytest

from roboprobe.core.errors import ValidationError
from roboprobe.scenario.constraints import compile_constraint

pytestmark = pytest.mark.security

_REJECTED = (
    "__import__('os')",
    "robot.speed.__class__",
    "(lambda: 1)()",
    "[x for x in (1,)]",
    "robot.speed ** 1000000 <= 1",
    "2 ** 100000 <= 1",
)


@pytest.mark.parametrize("expr", _REJECTED)
def test_injection_and_huge_exponent_rejected(expr: str) -> None:
    with pytest.raises(ValidationError):
        compile_constraint(expr)


def test_variable_exponent_still_evaluates() -> None:
    assert bool(compile_constraint("10 ** robot.speed > 1").evaluate({"robot.speed": 1.0}))
