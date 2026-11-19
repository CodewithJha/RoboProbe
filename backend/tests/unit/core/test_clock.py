from datetime import UTC, datetime, timedelta, timezone

import pytest

from roboprobe.core.clock import Clock, FakeClock, SystemClock

pytestmark = pytest.mark.unit

START = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("clock", [SystemClock(), FakeClock(START)])
def test_implementations_satisfy_protocol(clock: Clock) -> None:
    assert isinstance(clock, Clock)


def test_system_clock_now_is_tz_aware_utc() -> None:
    now = SystemClock().now()
    assert now.tzinfo is UTC


def test_system_clock_monotonic_non_decreasing() -> None:
    clock = SystemClock()
    first = clock.monotonic()
    clock.sleep(0)
    assert clock.monotonic() >= first


def test_system_clock_rejects_negative_sleep() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        SystemClock().sleep(-1)


def test_fake_clock_is_frozen_until_advanced() -> None:
    clock = FakeClock(START, monotonic_start=100.0)
    assert clock.now() == START
    assert clock.monotonic() == 100.0
    assert clock.now() == START


def test_fake_clock_advance_moves_now_and_monotonic() -> None:
    clock = FakeClock(START)
    clock.advance(1.5)
    assert clock.now() == START + timedelta(seconds=1.5)
    assert clock.monotonic() == 1.5


def test_fake_clock_sleep_advances_instantly() -> None:
    clock = FakeClock(START)
    clock.sleep(30)
    assert clock.now() == START + timedelta(seconds=30)
    assert clock.monotonic() == 30


def test_fake_clock_normalises_start_to_utc() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    clock = FakeClock(datetime(2026, 11, 20, 17, 30, tzinfo=ist))
    assert clock.now() == START
    assert clock.now().tzinfo is UTC


def test_fake_clock_rejects_naive_start() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FakeClock(datetime(2026, 11, 20))  # naive on purpose


@pytest.mark.parametrize("method", ["advance", "sleep"])
def test_fake_clock_rejects_negative_durations(method: str) -> None:
    clock = FakeClock(START)
    with pytest.raises(ValueError, match="non-negative"):
        getattr(clock, method)(-0.1)
    assert clock.now() == START
