"""Unit tests for :mod:`roboprobe.geometry.grid`."""

from __future__ import annotations

import math

import numpy as np
import pytest

from roboprobe.geometry import OccupancyGrid

pytestmark = pytest.mark.unit

RES = 0.05


def wall_grid() -> OccupancyGrid:
    """2 x 2 m grid (x in [-1, 1], y in [2, 4]) with a wall in column 10 (x in [-0.5, -0.45])."""
    occupied = np.zeros((40, 40), dtype=bool)
    occupied[:, 10] = True
    return OccupancyGrid(occupied, RES, origin=(-1.0, 2.0))


def test_world_cell_round_trip() -> None:
    grid = wall_grid()
    cells = np.array([[0, 0], [5, 7], [39, 39]])
    np.testing.assert_array_equal(grid.world_to_cell(grid.cell_to_world(cells)), cells)
    np.testing.assert_allclose(grid.cell_to_world([0, 0]), [-1.0 + RES / 2, 2.0 + RES / 2])


def test_rows_follow_y_and_columns_follow_x() -> None:
    grid = wall_grid()
    np.testing.assert_array_equal(grid.world_to_cell([-1.0 + 0.26, 2.0 + 0.11]), [2, 5])


def test_contains_and_outside_is_zero_distance() -> None:
    grid = wall_grid()
    points = np.array([[-1.5, 2.5], [-0.5, 2.5], [0.99, 3.99], [0.5, 4.0]])
    assert grid.contains(points).tolist() == [False, True, True, False]
    assert grid.distance_at(points)[0] == 0.0
    assert grid.distance_at(points)[3] == 0.0


def test_distance_to_a_wall_is_within_one_cell() -> None:
    grid = wall_grid()
    left_face, right_face = -1.0 + 10 * RES, -1.0 + 11 * RES
    for gap in (0.1, 0.37):
        assert grid.distance_at([left_face - gap, 3.0]) == pytest.approx(gap, abs=RES)
    for gap in (0.1, 0.37, 0.8):
        assert grid.distance_at([right_face + gap, 3.0]) == pytest.approx(gap, abs=RES)
    assert grid.distance_at([left_face + RES / 2, 3.0]) == 0.0


def test_distance_field_is_read_only_and_matches_shape() -> None:
    grid = wall_grid()
    assert grid.distance_field.shape == grid.shape == (40, 40)
    with pytest.raises(ValueError, match="read-only"):
        grid.distance_field[0, 0] = 1.0


def test_empty_grid_has_infinite_clearance() -> None:
    grid = OccupancyGrid(np.zeros((3, 3), dtype=bool), RES)
    assert np.isinf(grid.distance_at([0.05, 0.05]))


def test_input_array_is_copied() -> None:
    occupied = np.zeros((3, 3), dtype=bool)
    grid = OccupancyGrid(occupied, RES)
    occupied[1, 1] = True
    assert not grid.occupied.any()


@pytest.mark.parametrize(
    ("occupied", "resolution", "origin", "match"),
    [
        (np.zeros(3, dtype=bool), RES, (0.0, 0.0), "2-D"),
        (np.zeros((0, 3), dtype=bool), RES, (0.0, 0.0), "non-empty"),
        (np.zeros((3, 3), dtype=bool), 0.0, (0.0, 0.0), "resolution"),
        (np.zeros((3, 3), dtype=bool), math.nan, (0.0, 0.0), "resolution"),
        (np.zeros((3, 3), dtype=bool), RES, (math.inf, 0.0), "origin"),
    ],
)
def test_invalid_grids_are_rejected(
    occupied: np.ndarray, resolution: float, origin: tuple[float, float], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        OccupancyGrid(occupied, resolution, origin)
