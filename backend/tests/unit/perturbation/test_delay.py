"""Tests for the command delay FIFO (T-031a; docs/06 §3.6)."""

from __future__ import annotations

import doctest
import math

import pytest

from roboprobe.perturbation import delay
from roboprobe.perturbation.delay import CommandDelayBuffer

pytestmark = pytest.mark.unit

DT = 0.05  # kinematic2d default step [s]


def test_command_applied_at_t_plus_delay() -> None:
    buf = CommandDelayBuffer[str](delay_s=0.14)
    buf.push(1.0, "a")
    assert buf.pop_due(1.13) == []
    assert buf.pop_due(1.14) == ["a"]
    assert len(buf) == 0


def test_zero_delay_is_passthrough() -> None:
    buf = CommandDelayBuffer[int](delay_s=0.0)
    buf.push(0.5, 7)
    assert buf.pop_due(0.5) == [7]


def test_fifo_order_and_partial_release() -> None:
    buf = CommandDelayBuffer[str](delay_s=0.1)
    buf.push(0.0, "c0")
    buf.push(0.0, "c1")
    buf.push(0.02, "c2")
    assert buf.pop_due(0.1) == ["c0", "c1"]
    buf.push(0.2, "c3")
    assert len(buf) == 2
    assert buf.pop_due(0.25) == ["c2"]
    assert buf.pop_due(0.3) == ["c3"]


def test_accumulated_float_steps_release_on_time() -> None:
    step, steps_until_due = 0.1, 8
    buf = CommandDelayBuffer[int](delay_s=step * steps_until_due)
    buf.push(0.0, 1)
    t = 0.0
    for _ in range(steps_until_due):
        t += step
    assert t < buf.delay_s  # 0.7999999999999999: binary float accumulation falls short
    assert buf.pop_due(t) == [1]


def test_simulation_loop_shifts_commands_by_delay() -> None:
    delay_steps = 3
    buf = CommandDelayBuffer[int](delay_s=delay_steps * DT)
    applied: list[int | None] = []
    current: int | None = None
    for step in range(10):
        t = step * DT
        buf.push(t, step)
        due = buf.pop_due(t)
        current = due[-1] if due else current
        applied.append(current)
    assert applied == [None, None, None, 0, 1, 2, 3, 4, 5, 6]


def test_clear_drops_pending_commands() -> None:
    buf = CommandDelayBuffer[int](delay_s=1.0)
    buf.push(0.0, 1)
    buf.clear()
    assert len(buf) == 0
    assert buf.pop_due(2.0) == []
    assert buf.delay_s == 1.0


@pytest.mark.parametrize(
    "kwargs", [{"delay_s": -0.1}, {"delay_s": math.nan}, {"delay_s": 0.1, "tolerance_s": -1.0}]
)
def test_invalid_construction(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="must be finite"):
        CommandDelayBuffer[int](**kwargs)


def test_time_must_not_go_backwards() -> None:
    buf = CommandDelayBuffer[int](delay_s=0.1)
    buf.push(1.0, 1)
    with pytest.raises(ValueError, match="backwards"):
        buf.push(0.5, 2)
    with pytest.raises(ValueError, match="backwards"):
        buf.pop_due(0.9)


@pytest.mark.parametrize("t", [math.nan, math.inf])
def test_time_must_be_finite(t: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        CommandDelayBuffer[int](delay_s=0.1).push(t, 1)


def test_docstring_example() -> None:
    assert doctest.testmod(delay).failed == 0
