"""Injectable time source so domain and application code never read the wall clock directly.

Layer: Kernel (L1). Code that needs the current time, a monotonic reading or a sleep takes a
:class:`Clock` as a dependency; production wiring passes :class:`SystemClock`, tests and
simulated experiments pass :class:`FakeClock`.

Implements: AGENTS.md §3 (determinism), FR-RUN-002 (fake-clock testable timing).
"""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

__all__ = ["Clock", "FakeClock", "SystemClock"]


@runtime_checkable
class Clock(Protocol):
    """Port for reading time and waiting.

    Implementations must return timezone-aware UTC datetimes from :meth:`now` and a
    non-decreasing float from :meth:`monotonic`.
    """

    def now(self) -> datetime:
        """Return the current time as a timezone-aware UTC datetime."""
        ...

    def monotonic(self) -> float:
        """Return a monotonic reading in seconds, suitable only for measuring intervals."""
        ...

    def sleep(self, seconds: float) -> None:
        """Block (or pretend to block) for ``seconds``.

        Args:
            seconds: Non-negative duration in seconds.
        """
        ...


class SystemClock:
    """Real clock backed by :mod:`datetime` and :mod:`time`."""

    def now(self) -> datetime:
        """Return the current wall-clock time in UTC (timezone-aware)."""
        return datetime.now(UTC)

    def monotonic(self) -> float:
        """Return :func:`time.monotonic`."""
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        """Sleep for ``seconds`` using :func:`time.sleep`.

        Args:
            seconds: Non-negative duration in seconds.

        Raises:
            ValueError: If ``seconds`` is negative or not finite.
        """
        _check_non_negative(seconds)
        time.sleep(seconds)


class FakeClock:
    """Deterministic manual clock for tests and simulated time.

    ``now`` and ``monotonic`` only move when :meth:`advance` or :meth:`sleep` is called, so
    timing logic (heartbeats, reaper, stop rules) can be tested without real waiting.

    ``now`` has :class:`~datetime.datetime` (microsecond) resolution while ``monotonic`` is a
    float, so sub-microsecond advances are visible only through ``monotonic``.
    """

    def __init__(self, start: datetime, monotonic_start: float = 0.0) -> None:
        """Create a fake clock.

        Args:
            start: Initial wall-clock time; must be timezone-aware. Stored as UTC.
            monotonic_start: Initial monotonic reading in seconds.

        Raises:
            ValueError: If ``start`` is naive (has no timezone).
        """
        if start.tzinfo is None or start.utcoffset() is None:
            msg = "FakeClock start must be timezone-aware"
            raise ValueError(msg)
        self._now = start.astimezone(UTC)
        self._monotonic = monotonic_start

    def now(self) -> datetime:
        """Return the simulated current time (timezone-aware UTC)."""
        return self._now

    def monotonic(self) -> float:
        """Return the simulated monotonic reading in seconds."""
        return self._monotonic

    def sleep(self, seconds: float) -> None:
        """Advance the clock by ``seconds`` immediately instead of blocking.

        Args:
            seconds: Non-negative duration in seconds.

        Raises:
            ValueError: If ``seconds`` is negative or not finite.
        """
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        """Move both ``now`` and ``monotonic`` forward by ``seconds``.

        Args:
            seconds: Non-negative duration in seconds.

        Raises:
            ValueError: If ``seconds`` is negative (time never runs backwards) or not finite.
        """
        _check_non_negative(seconds)
        self._now += timedelta(seconds=seconds)
        self._monotonic += seconds


def _check_non_negative(seconds: float) -> None:
    if not math.isfinite(seconds) or seconds < 0:
        msg = f"duration must be finite and non-negative, got {seconds!r}"
        raise ValueError(msg)
