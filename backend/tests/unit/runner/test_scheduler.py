"""Scheduler target_inflight (T-041a)."""

from __future__ import annotations

import math

import pytest

from roboprobe.core.settings.runner import RunnerSettings
from roboprobe.runner.scheduler import Scheduler

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("workers", "batch", "factor", "expected"),
    [
        (0, 8, 1.5, 0),
        (4, 8, 1.5, math.ceil(4 * 1.5)),
        (10, 8, 1.5, math.ceil(8 * 1.5)),
        (2, 100, 1.5, math.ceil(2 * 1.5)),  # max_batch_size default 32 → min(32,2)=2
        (4, 8, 2.0, 8),
    ],
)
def test_target_inflight(workers: int, batch: int, factor: float, expected: int) -> None:
    sched = Scheduler(RunnerSettings(inflight_factor=factor, max_batch_size=32))
    assert sched.target_inflight(workers, batch) == expected
