"""Unit and property tests for :mod:`roboprobe.geometry.distance` (docs/10 §6)."""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt
import pytest
from hypothesis import given
from hypothesis import strategies as st

from roboprobe.geometry import (
    CircleFootprint,
    OccupancyGrid,
    PolygonFootprint,
    Rect,
    footprint_grid_distance,
    footprint_rect_distance,
    min_obstacle_distance,
    point_rect_distance,
    point_segment_distance,
    polygon_distance,
)

pytestmark = pytest.mark.unit

TB4_RADIUS = 0.17
ANALYTIC_TOL = 1e-9
RES = 0.05
PALLET = Rect(x=2.0, y=0.0, yaw=0.0, length=0.8, width=0.6)  # spans x 1.6..2.4, y -0.3..0.3
DISC = CircleFootprint(TB4_RADIUS)
BOX = PolygonFootprint(np.array([[0.2, 0.15], [-0.2, 0.15], [-0.2, -0.15], [0.2, -0.15]]))


def rasterise(rect: Rect, size: int = 120) -> OccupancyGrid:
    """Grid with origin (-1, -3) whose cells are occupied when their centre lies in ``rect``."""
    probe = OccupancyGrid(np.zeros((size, size), dtype=bool), RES, origin=(-1.0, -3.0))
    rows, cols = np.indices((size, size))
    centres = probe.cell_to_world(np.stack([rows, cols], axis=-1))
    return OccupancyGrid(point_rect_distance(centres, rect) == 0, RES, origin=(-1.0, -3.0))


# --------------------------------------------------------------------------- primitives


def test_point_segment_distance_cases() -> None:
    a, b = np.array([0.0, 0.0]), np.array([2.0, 0.0])
    points = np.array([[1.0, 1.0], [-3.0, 4.0], [5.0, 0.0], [1.0, 0.0]])
    np.testing.assert_allclose(point_segment_distance(points, a, b), [1.0, 5.0, 3.0, 0.0])
    assert point_segment_distance([3.0, 4.0], a, a) == pytest.approx(5.0)  # degenerate


def test_point_rect_distance_rotated() -> None:
    rect = Rect(x=0.0, y=0.0, yaw=math.pi / 4, length=2.0, width=2.0)
    assert point_rect_distance([0.0, 0.0], rect) == 0.0
    assert point_rect_distance([0.0, 2.0], rect) == pytest.approx(2.0 - math.sqrt(2))
    assert point_rect_distance([2.0, 0.0], rect) == pytest.approx(2.0 - math.sqrt(2))


def test_rect_corners_counter_clockwise() -> None:
    corners = Rect(x=1.0, y=1.0, yaw=math.pi / 2, length=2.0, width=1.0).corners()
    np.testing.assert_allclose(
        corners, [[0.5, 2.0], [0.5, 0.0], [1.5, 0.0], [1.5, 2.0]], atol=1e-12
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"length": 0.0},
        {"width": -1.0},
        {"yaw": math.nan},
        {"x": math.inf},
    ],
)
def test_invalid_rects_are_rejected(kwargs: dict[str, float]) -> None:
    fields = {"x": 0.0, "y": 0.0, "yaw": 0.0, "length": 1.0, "width": 1.0} | kwargs
    with pytest.raises(ValueError, match="rectangle"):
        Rect(**fields)


# --------------------------------------------------------------------------- disc vs rectangle


@pytest.mark.parametrize(
    ("pose", "expected"),
    [
        ((1.0, 0.0, 0.0), 0.6 - TB4_RADIUS),  # in front of the near face
        ((2.0, 1.0, 1.3), 0.7 - TB4_RADIUS),  # beside the long face; yaw is irrelevant
        ((3.0, 1.1, 0.0), math.hypot(0.6, 0.8) - TB4_RADIUS),  # off the corner
        ((1.5, 0.0, 0.0), 0.0),  # overlapping
        ((2.0, 0.0, 0.0), 0.0),  # centre inside
        ((1.6 - TB4_RADIUS, 0.0, 0.0), 0.0),  # touching
    ],
)
def test_disc_to_rectangle_is_analytic(pose: tuple[float, float, float], expected: float) -> None:
    assert footprint_rect_distance(DISC, [pose], PALLET)[0] == pytest.approx(
        expected, abs=ANALYTIC_TOL
    )


@pytest.mark.parametrize("gap", [0.05, 0.2, 0.43, 1.0])
def test_disc_to_rasterised_rectangle_is_within_one_cell(gap: float) -> None:
    grid = rasterise(PALLET)
    poses = np.array([[1.6 - TB4_RADIUS - gap, 0.0, 0.0], [2.0, 0.3 + TB4_RADIUS + gap, 0.0]])
    distances = footprint_grid_distance(DISC, poses, grid)
    np.testing.assert_allclose(distances, [gap, gap], atol=RES)


# --------------------------------------------------------------------------- polygons


def square(cx: float, cy: float, half: float = 0.5) -> npt.NDArray[np.float64]:
    return np.array([[cx + half, cy + half], [cx - half, cy + half], [cx - half, cy - half],
                     [cx + half, cy - half]])  # fmt: skip


@pytest.mark.parametrize(
    ("b", "expected"),
    [
        (square(3.0, 0.0), 2.0),  # separated along x
        (square(2.0, 2.0), math.hypot(1.0, 1.0)),  # corner to corner
        (square(1.0, 0.0), 0.0),  # sharing an edge
        (square(0.2, 0.1, 0.1), 0.0),  # contained
        (square(0.0, 0.0, 3.0), 0.0),  # containing
        (
            np.array([[-2.0, 0.1], [2.0, 0.1], [2.0, -0.1], [-2.0, -0.1]]),
            0.0,
        ),  # crossing, no vertex inside
    ],
)
def test_polygon_distance_cases(b: npt.NDArray[np.float64], expected: float) -> None:
    a = square(0.0, 0.0)
    assert polygon_distance(a[None], b[None])[0] == pytest.approx(expected, abs=ANALYTIC_TOL)
    assert polygon_distance(b[None], a[None])[0] == pytest.approx(expected, abs=ANALYTIC_TOL)


def test_box_footprint_to_rectangle_rotated() -> None:
    # rotated 90°: half-extent along x becomes 0.15
    poses = np.array([[1.0, 0.0, 0.0], [1.0, 0.0, math.pi / 2], [2.0, 0.0, 0.3]])
    np.testing.assert_allclose(
        footprint_rect_distance(BOX, poses, PALLET), [0.4, 0.45, 0.0], atol=ANALYTIC_TOL
    )


def test_box_footprint_to_rasterised_rectangle_is_within_one_cell() -> None:
    grid = rasterise(PALLET)
    poses = np.array([[1.0, 0.0, 0.0], [1.0, 0.0, math.pi / 2], [2.0, 0.0, 0.3], [0.5, 1.0, 0.7]])
    np.testing.assert_allclose(
        footprint_grid_distance(BOX, poses, grid),
        footprint_rect_distance(BOX, poses, PALLET),
        atol=RES,
    )


def test_small_obstacle_inside_a_polygon_footprint_is_detected() -> None:
    occupied = np.zeros((40, 40), dtype=bool)
    occupied[20, 20] = True  # one cell at world (1.0..1.05, 1.0..1.05)
    grid = OccupancyGrid(occupied, RES)
    big = PolygonFootprint(square(0.0, 0.0, 0.4))
    assert footprint_grid_distance(big, [[1.02, 1.02, 0.0]], grid)[0] == 0.0


@given(
    x=st.floats(-1.0, 4.0),
    y=st.floats(-2.0, 2.0),
    yaw=st.floats(-math.pi, math.pi),
)
def test_polygon_footprint_never_reports_more_than_the_inscribed_disc(
    x: float, y: float, yaw: float
) -> None:
    inner = CircleFootprint(0.15)  # inscribed in BOX
    outer = CircleFootprint(math.hypot(0.2, 0.15))  # circumscribed
    pose = [[x, y, yaw]]
    box = footprint_rect_distance(BOX, pose, PALLET)[0]
    assert footprint_rect_distance(outer, pose, PALLET)[0] - ANALYTIC_TOL <= box
    assert box <= footprint_rect_distance(inner, pose, PALLET)[0] + ANALYTIC_TOL


# --------------------------------------------------------------------------- combined


def test_min_obstacle_distance_takes_the_nearest_obstacle() -> None:
    occupied = np.zeros((120, 120), dtype=bool)
    occupied[:, 0] = True  # wall at world x = -1.0..-0.95
    grid = OccupancyGrid(occupied, RES, origin=(-1.0, -3.0))
    poses = np.array([[1.0, 0.0, 0.0], [-0.5, 0.0, 0.0]])
    distances = min_obstacle_distance(DISC, poses, grid, [PALLET])
    np.testing.assert_allclose(distances, [0.6 - TB4_RADIUS, 0.45 - TB4_RADIUS], atol=RES)


def test_min_obstacle_distance_without_obstacles_is_infinite() -> None:
    assert np.isinf(min_obstacle_distance(DISC, np.zeros((2, 3)))).all()


def test_vectorised_over_many_poses() -> None:
    rng = np.random.default_rng(0)
    n = 500
    poses = np.column_stack([rng.uniform(-1, 4, n), rng.uniform(-2, 2, n), rng.uniform(-3, 3, n)])
    batch = min_obstacle_distance(BOX, poses, rects=[PALLET])
    single = [min_obstacle_distance(BOX, pose, rects=[PALLET])[0] for pose in poses[:20]]
    assert batch.shape == (n,)
    np.testing.assert_allclose(batch[:20], single)
