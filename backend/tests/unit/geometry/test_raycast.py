"""Unit and property tests for :mod:`roboprobe.geometry.raycast` (docs/10 §7.1)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from roboprobe.geometry import (
    BeamSpec,
    GridRayCaster,
    OccupancyGrid,
    Rect,
    cast,
    point_rect_distance,
)

pytestmark = pytest.mark.unit

RES = 0.05
R_MIN, R_MAX = 0.15, 12.0
ROOM = 200  # cells: a 10 m x 10 m room with walls on the border cells, origin (0, 0)
EAST, NORTH, WEST, SOUTH = 0.0, math.pi / 2, math.pi, -math.pi / 2


def room() -> OccupancyGrid:
    occupied = np.zeros((ROOM, ROOM), dtype=bool)
    occupied[0, :] = occupied[-1, :] = occupied[:, 0] = occupied[:, -1] = True
    return OccupancyGrid(occupied, RES)


def beams(*angles: float, r_min: float = R_MIN, r_max: float = R_MAX) -> BeamSpec:
    return BeamSpec(np.array(angles), r_min, r_max)


INNER = RES  # inner faces of the border walls are at 0.05 m and 9.95 m


def test_axis_aligned_walls_are_exact() -> None:
    ranges = GridRayCaster(room()).cast([3.0, 4.0, 0.0], beams(EAST, NORTH, WEST, SOUTH))
    np.testing.assert_allclose(
        ranges, [9.95 - 3.0, 9.95 - 4.0, 3.0 - INNER, 4.0 - INNER], atol=1e-9
    )


@given(
    x=st.floats(0.5, 9.5),
    y=st.floats(0.5, 9.5),
    angle=st.floats(-math.pi, math.pi),
)
def test_oblique_beams_hit_the_room_walls_within_one_cell(x: float, y: float, angle: float) -> None:
    caster = GridRayCaster(room())
    measured = caster.cast([x, y, 0.0], beams(angle))[0]
    dx, dy = math.cos(angle), math.sin(angle)
    candidates = []
    for wall, origin, d in ((9.95, x, dx), (INNER, x, dx), (9.95, y, dy), (INNER, y, dy)):
        if d != 0 and (t := (wall - origin) / d) > 0:
            candidates.append(t)
    assert measured == pytest.approx(min(*candidates, R_MAX), abs=RES)


def test_heading_rotates_the_fan() -> None:
    caster = GridRayCaster(room())
    rotated = caster.cast([3.0, 4.0, NORTH], beams(0.0, -NORTH))
    np.testing.assert_allclose(rotated, [9.95 - 4.0, 9.95 - 3.0], atol=1e-9)


def test_rectangles_are_analytic_and_can_be_excluded() -> None:
    pallet = Rect(x=6.0, y=4.0, yaw=0.0, length=0.8, width=0.6)
    caster = GridRayCaster(room())
    spec = beams(EAST, NORTH)
    seen = caster.cast([3.0, 4.0, 0.0], spec, [pallet])
    np.testing.assert_allclose(seen, [5.6 - 3.0, 9.95 - 4.0], atol=1e-9)
    blind = caster.cast([3.0, 4.0, 0.0], spec, [pallet], include_rects=False)
    np.testing.assert_allclose(blind, [9.95 - 3.0, 9.95 - 4.0], atol=1e-9)


def test_rotated_rectangle_hit() -> None:
    diamond = Rect(x=6.0, y=4.0, yaw=math.pi / 4, length=1.0, width=1.0)
    ranges = GridRayCaster(room()).cast([3.0, 4.0, 0.0], beams(EAST), [diamond])
    assert ranges[0] == pytest.approx(3.0 - math.sqrt(0.5), abs=1e-9)


def test_ranges_are_clipped_to_the_limits() -> None:
    caster = GridRayCaster(room())
    short = caster.cast([3.0, 4.0, 0.0], beams(EAST, WEST, r_max=2.0))
    np.testing.assert_allclose(short, [2.0, 2.0])
    inside_wall = caster.cast([0.02, 4.0, 0.0], beams(EAST, WEST))
    np.testing.assert_allclose(inside_wall, [R_MIN, R_MIN])
    inside_rect = caster.cast([3.0, 4.0, 0.0], beams(EAST), [Rect(3.0, 4.0, 0.0, 1.0, 1.0)])
    np.testing.assert_allclose(inside_rect, [R_MIN])


def test_beams_leaving_the_grid_see_free_space() -> None:
    occupied = np.zeros((20, 20), dtype=bool)
    occupied[10, 15] = True
    grid = OccupancyGrid(occupied, RES, origin=(-0.5, -0.5))
    ranges = GridRayCaster(grid).cast([0.0, 0.0, 0.0], beams(EAST, WEST, NORTH))
    assert ranges[0] == pytest.approx(0.25, abs=1e-9)  # cell (10, 15) spans x 0.25..0.30
    np.testing.assert_allclose(ranges[1:], [R_MAX, R_MAX])


def test_sensor_outside_the_grid_can_see_into_it() -> None:
    ranges = GridRayCaster(room()).cast([-2.0, 4.0, 0.0], beams(EAST, WEST))
    np.testing.assert_allclose(ranges, [2.0, R_MAX], atol=1e-9)


def test_convenience_function_matches_the_caster() -> None:
    grid, spec = room(), beams(*np.linspace(-math.pi, math.pi, 37))
    pallet = [Rect(6.0, 4.0, 0.3, 0.8, 0.6)]
    np.testing.assert_array_equal(
        cast(grid, [3.0, 4.0, 0.2], spec, pallet),
        GridRayCaster(grid).cast([3.0, 4.0, 0.2], spec, pallet),
    )
    assert GridRayCaster(grid).grid is grid


@given(x=st.floats(1.0, 4.0), y=st.floats(1.0, 9.0), heading=st.floats(-math.pi, math.pi))
def test_rasterised_rectangle_matches_the_analytic_one(x: float, y: float, heading: float) -> None:
    pallet = Rect(x=6.0, y=5.0, yaw=0.4, length=1.6, width=1.2)
    grid = room()
    rows, cols = np.indices(grid.shape)
    centres = grid.cell_to_world(np.stack([rows, cols], axis=-1))
    raster = OccupancyGrid(grid.occupied | (point_rect_distance(centres, pallet) == 0), RES)
    spec = beams(*np.linspace(-0.3, 0.3, 7))
    analytic = GridRayCaster(grid).cast([x, y, heading], spec, [pallet])
    rasterised = GridRayCaster(raster).cast([x, y, heading], spec)
    # The staircase boundary differs from the true edge by up to a cell *perpendicular* to it, which
    # grazing beams stretch along the ray; so compare hit points, not ranges.
    headings = heading + spec.angles
    hits = np.array([x, y]) + rasterised[:, None] * np.column_stack(
        [np.cos(headings), np.sin(headings)]
    )
    walls = GridRayCaster(grid).cast([x, y, heading], spec)
    # A beam grazing a corner may hit only one of the two shapes; compare beams that hit both.
    on_pallet = (analytic < walls) & (rasterised < walls)
    assert np.all(point_rect_distance(hits[on_pallet], pallet) <= RES * math.sqrt(2))


@pytest.mark.parametrize(
    ("angles", "r_min", "r_max", "match"),
    [
        ([], R_MIN, R_MAX, "non-empty"),
        ([[0.0]], R_MIN, R_MAX, "1-D"),
        ([math.nan], R_MIN, R_MAX, "finite"),
        ([0.0], -0.1, R_MAX, "r_min"),
        ([0.0], 2.0, 1.0, "r_min"),
        ([0.0], 0.0, math.inf, "finite"),
    ],
)
def test_invalid_beam_specs_are_rejected(
    angles: list[float], r_min: float, r_max: float, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        BeamSpec(np.array(angles), r_min, r_max)


def test_beam_angles_are_read_only_copies() -> None:
    angles = np.array([0.0, 1.0])
    spec = BeamSpec(angles, R_MIN, R_MAX)
    angles[0] = 5.0
    assert spec.angles[0] == 0.0
    with pytest.raises(ValueError, match="read-only"):
        spec.angles[0] = 1.0


@pytest.mark.parametrize("pose", [[0.0, 0.0], [0.0, 0.0, math.inf], [[0.0, 0.0, 0.0]]])
def test_invalid_poses_are_rejected(pose: object) -> None:
    with pytest.raises(ValueError, match="pose"):
        GridRayCaster(room()).cast(pose, beams(EAST))  # type: ignore[arg-type]
