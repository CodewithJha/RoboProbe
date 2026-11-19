"""Unit tests for :mod:`roboprobe.geometry.footprint`."""

from __future__ import annotations

import math

import numpy as np
import pytest

from roboprobe.geometry import CircleFootprint, PolygonFootprint

pytestmark = pytest.mark.unit

SQUARE = np.array([[0.2, 0.1], [-0.2, 0.1], [-0.2, -0.1], [0.2, -0.1]])


def test_circle_centres_follow_the_poses() -> None:
    poses = np.array([[1.0, 2.0, 0.3], [-1.0, 0.0, 3.0]])
    np.testing.assert_array_equal(CircleFootprint(0.17).centres(poses), poses[:, :2])


def test_single_pose_is_promoted_to_a_batch() -> None:
    assert CircleFootprint(0.17).centres([1.0, 2.0, 0.0]).shape == (1, 2)


@pytest.mark.parametrize("radius", [0.0, -0.1, math.inf, math.nan])
def test_circle_radius_must_be_positive_and_finite(radius: float) -> None:
    with pytest.raises(ValueError, match="radius"):
        CircleFootprint(radius)


def test_polygon_is_rotated_then_translated() -> None:
    world = PolygonFootprint(SQUARE).at([[1.0, 1.0, math.pi / 2]])
    expected = np.array([[0.9, 1.2], [0.9, 0.8], [1.1, 0.8], [1.1, 1.2]])
    np.testing.assert_allclose(world[0], expected, atol=1e-12)


def test_polygon_batch_shape() -> None:
    assert PolygonFootprint(SQUARE).at(np.zeros((5, 3))).shape == (5, 4, 2)


def test_polygon_vertices_are_read_only_copies() -> None:
    source = SQUARE.copy()
    footprint = PolygonFootprint(source)
    source[0, 0] = 9.0
    assert footprint.vertices[0, 0] == pytest.approx(0.2)
    with pytest.raises(ValueError, match="read-only"):
        footprint.vertices[0, 0] = 1.0


@pytest.mark.parametrize(
    "vertices", [np.zeros((2, 2)), np.zeros(3), np.zeros((4, 3)), [[0, 0], [1, 0], [0, math.inf]]]
)
def test_invalid_polygons_are_rejected(vertices: object) -> None:
    with pytest.raises(ValueError, match=r"vertex|vertices"):
        PolygonFootprint(vertices)  # type: ignore[arg-type]


@pytest.mark.parametrize("poses", [np.zeros((2, 2)), [[0.0, 0.0, math.nan]], np.zeros((1, 2, 3))])
def test_invalid_poses_are_rejected(poses: object) -> None:
    with pytest.raises(ValueError, match="poses"):
        CircleFootprint(0.1).centres(poses)  # type: ignore[arg-type]
