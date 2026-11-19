"""NFR-PERF-001 gate for the kinematic2d lidar ray caster (T-030b)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
import yaml
from pytest_benchmark.fixture import BenchmarkFixture

from roboprobe.geometry import BeamSpec, GridRayCaster, OccupancyGrid, Rect

pytestmark = pytest.mark.benchmark

THRESHOLDS = yaml.safe_load((Path(__file__).parent / "thresholds.yaml").read_text(encoding="utf-8"))
LIDAR_BEAMS = 180
RES = 0.05


def warehouse() -> OccupancyGrid:
    """20 m x 20 m hall with an outer wall and four 12 m shelf rows (2.5 m aisles)."""
    occupied = np.zeros((400, 400), dtype=bool)
    occupied[0, :] = occupied[-1, :] = occupied[:, 0] = occupied[:, -1] = True
    for row in range(60, 340, 70):
        occupied[row : row + 20, 80:320] = True
    return OccupancyGrid(occupied, RES)


def test_lidar_cast_meets_the_budget(benchmark: BenchmarkFixture) -> None:
    caster = GridRayCaster(warehouse())
    lidar = BeamSpec(np.linspace(-math.pi, math.pi, LIDAR_BEAMS, endpoint=False), 0.15, 12.0)
    pallet = [Rect(x=10.0, y=4.6, yaw=0.0, length=0.8, width=0.6)]
    pose = np.array([3.0, 4.6, 0.1])  # in an aisle, looking down it

    ranges = benchmark(caster.cast, pose, lidar, pallet, include_rects=False)

    assert ranges.shape == (LIDAR_BEAMS,)
    if benchmark.stats is not None:  # None when benchmarks are disabled (e.g. under xdist)
        median = benchmark.stats.stats.median
        assert median <= THRESHOLDS["raycast"]["lidar_180_beams_median_s"]
