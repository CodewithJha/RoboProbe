"""Verify Gazebo worker capacity without constraining other backends."""

import pytest

from roboprobe.bootstrap.worker import worker_slot_count
from roboprobe.core.settings import RoboProbeSettings


@pytest.mark.parametrize(
    ("backend", "requested", "expected"),
    [("gazebo_nav2", 6, 2), ("gazebo_nav2", 1, 1), ("kinematic2d", 6, 6)],
)
def test_worker_slot_cap(backend: str, requested: int, expected: int) -> None:
    settings = RoboProbeSettings.model_validate(
        {"worker": {"backend": backend}, "backends": {"gazebo_nav2": {"max_parallel_per_host": 2}}}
    )
    assert worker_slot_count(settings, requested) == expected
