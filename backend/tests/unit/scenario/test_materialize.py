"""Unit tests for :mod:`roboprobe.scenario.materialize` (docs/06 §3.2, FR-SCN-005)."""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from roboprobe.core import errors
from roboprobe.core.types import Pose2D
from roboprobe.scenario.materialize import Side, place_obstacle, render_template, side_sign

pytestmark = pytest.mark.unit

STRAIGHT = [(0.0, 0.0), (10.0, 0.0)]
L_SHAPED = [(0.0, 0.0), (4.0, 0.0), (4.0, 6.0)]  # length 10, corner at s = 4


def assert_pose(pose: Pose2D, x: float, y: float, yaw: float) -> None:
    assert (pose.x, pose.y, pose.yaw) == pytest.approx((x, y, yaw), abs=1e-12)


# --------------------------------------------------------------------------- place_obstacle


@pytest.mark.parametrize(
    ("along", "clearance", "side", "expected"),
    [
        (0.5, 0.8, 1, (5.0, 0.8, 0.0)),
        (0.5, 0.8, -1, (5.0, -0.8, 0.0)),
        (0.0, 0.0, 1, (0.0, 0.0, 0.0)),
        (1.0, 0.3, 1, (10.0, 0.3, 0.0)),
    ],
)
def test_straight_path(
    along: float, clearance: float, side: Side, expected: tuple[float, float, float]
) -> None:
    assert_pose(place_obstacle(STRAIGHT, along, clearance, side), *expected)


def test_l_shaped_path_first_leg_second_leg_and_corner() -> None:
    assert_pose(place_obstacle(L_SHAPED, 0.2, 0.5, 1), 2.0, 0.5, 0.0)
    # second leg heads +y; left normal is -x
    assert_pose(place_obstacle(L_SHAPED, 0.7, 0.5, 1), 3.5, 3.0, math.pi / 2)
    assert_pose(place_obstacle(L_SHAPED, 0.7, 0.5, -1), 4.5, 3.0, math.pi / 2)
    # exactly at the corner the outgoing segment defines the heading
    assert_pose(place_obstacle(L_SHAPED, 0.4, 0.5, 1), 3.5, 0.0, math.pi / 2)
    assert_pose(place_obstacle(L_SHAPED, 1.0, 0.0, 1), 4.0, 6.0, math.pi / 2)


def test_repeated_points_are_ignored() -> None:
    path = [(0.0, 0.0), (0.0, 0.0), (4.0, 0.0), (4.0, 0.0), (4.0, 6.0)]
    assert place_obstacle(path, 0.7, 0.5, 1) == place_obstacle(L_SHAPED, 0.7, 0.5, 1)


def test_diagonal_path_yaw_and_normal() -> None:
    pose = place_obstacle([(0.0, 0.0), (3.0, 4.0)], 1.0, 5.0, 1)
    assert_pose(pose, 3.0 - 4.0, 4.0 + 3.0, math.atan2(4.0, 3.0))


@given(
    along=st.floats(0, 1),
    clearance=st.floats(0, 5),
    side=st.sampled_from([-1, 1]),
)
def test_obstacle_is_exactly_clearance_from_the_path_point(
    along: float, clearance: float, side: Side
) -> None:
    centre = place_obstacle(L_SHAPED, along, clearance, side)
    on_path = place_obstacle(L_SHAPED, along, 0.0, side)
    assert math.dist((centre.x, centre.y), (on_path.x, on_path.y)) == pytest.approx(clearance)
    assert centre.yaw == on_path.yaw


@pytest.mark.parametrize(
    ("path", "match"),
    [
        ([(0.0, 0.0)], "at least two distinct"),
        ([(1.0, 1.0), (1.0, 1.0)], "at least two distinct"),
        ([0.0, 1.0], r"\(n, 2\)"),
        ([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], r"\(n, 2\)"),
        ([(0.0, 0.0), (math.nan, 1.0)], "finite"),
    ],
)
def test_malformed_paths_are_rejected(path: object, match: str) -> None:
    with pytest.raises(errors.ValidationError, match=match):
        place_obstacle(path, 0.5, 0.1, 1)  # type: ignore[arg-type]


def test_out_of_range_arguments_are_all_reported() -> None:
    with pytest.raises(errors.ValidationError) as exc:
        place_obstacle(STRAIGHT, 1.5, -1.0, 0)  # type: ignore[arg-type]
    assert len(exc.value.context["problems"]) == 3  # type: ignore[arg-type]


@pytest.mark.parametrize("clearance", [math.inf, math.nan])
def test_non_finite_clearance_is_rejected(clearance: float) -> None:
    with pytest.raises(errors.ValidationError, match="clearance"):
        place_obstacle(STRAIGHT, 0.5, clearance, 1)


def test_side_sign_maps_task_file_sides() -> None:
    assert side_sign("left") == 1
    assert side_sign("right") == -1


# --------------------------------------------------------------------------- render_template


def test_render_substitutes_and_keeps_trailing_newline() -> None:
    template = "<pose>{{ x }} {{ y }} 0 0 0 {{ yaw }}</pose>\n"
    assert render_template(template, {"x": 1.5, "y": -2, "yaw": 0.25}) == (
        "<pose>1.5 -2 0 0 0 0.25</pose>\n"
    )


def test_render_does_not_escape_markup() -> None:
    assert render_template("{{ v }}", {"v": "<a & b>"}) == "<a & b>"


def test_rendering_twice_gives_identical_bytes() -> None:
    template = "{% for k, v in params|dictsort %}{{ k }}: {{ v }}\n{% endfor %}"
    ctx = {"params": {"b": 0.1 + 0.2, "a": 1e-7, "c": "x"}}
    first = render_template(template, ctx).encode()
    assert first == render_template(template, dict(ctx)).encode()
    assert first == b"a: 1e-07\nb: 0.30000000000000004\nc: x\n"


@pytest.mark.parametrize(
    ("template", "match"),
    [
        ("{{ missing }}", "UndefinedError: 'missing' is undefined"),
        ("{{ obj.missing }}", "UndefinedError"),
        ("{% for %}", "TemplateSyntaxError"),
        ("{{ ''.__class__.__mro__ }}", "SecurityError"),
        ("{{ f.__globals__ }}", "SecurityError|UndefinedError"),
    ],
)
def test_render_failures_are_validation_errors(template: str, match: str) -> None:
    with pytest.raises(errors.ValidationError, match=match):
        render_template(template, {"obj": object(), "f": render_template})
