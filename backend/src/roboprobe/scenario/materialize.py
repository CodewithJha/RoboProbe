"""Backend-agnostic materialisation helpers: template rendering and obstacle placement.

Both simulator backends use these so kinematic2d and Gazebo place obstacles identically
(cross-backend parity, docs/08 §7) and render world/parameter files byte-identically for equal
inputs (FR-SCN-005).

* :func:`render_template` renders a Jinja2 template in a **sandboxed** environment with
  ``StrictUndefined``: a missing variable fails at render time instead of producing an empty string,
  and templates cannot reach Python internals (docs/31).
* :func:`place_obstacle` implements docs/06 §3.2: ``c = path(s) + side · n(s) · clearance`` with
  ``s = along · L_path``, ``n(s)`` the left unit normal and the yaw aligned with the path tangent.

Layer: Domain (L2).

Implements: FR-SCN-005, docs/06 §3.2
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from functools import cache
from typing import Final, Literal

import jinja2
import numpy as np
import numpy.typing as npt
from jinja2.sandbox import SandboxedEnvironment

from roboprobe.core import errors
from roboprobe.core.types import JsonValue, Pose2D

__all__ = ["Side", "place_obstacle", "render_template", "side_sign"]

Side = Literal[-1, 1]
"""``+1`` places the obstacle left of the travel direction, ``-1`` right."""

_SIDE_SIGNS: Final[Mapping[str, Side]] = {"left": 1, "right": -1}
_POINT_DIM: Final = 2


@cache
def _environment() -> SandboxedEnvironment:
    return SandboxedEnvironment(
        undefined=jinja2.StrictUndefined,
        # Output is SDF/YAML/parameter files, never HTML, so escaping would corrupt it.
        autoescape=False,
        keep_trailing_newline=True,
    )


def render_template(template: str, ctx: Mapping[str, object]) -> str:
    """Render ``template`` with ``ctx`` (sandboxed Jinja2, ``StrictUndefined``).

    Rendering is a pure function of its inputs, so equal inputs give byte-identical output.

    Raises:
        roboprobe.core.errors.ValidationError: On a syntax error, an undefined variable or an
            operation the sandbox forbids.
    """
    try:
        return _environment().from_string(template).render(ctx)
    except jinja2.TemplateError as exc:  # syntax, undefined and sandbox security errors
        reason = f"{type(exc).__name__}: {exc.message or exc}"
        msg = f"template rendering failed: {reason}"
        raise errors.ValidationError(msg, context={"reason": reason}) from exc


def side_sign(side: Literal["left", "right"]) -> Side:
    """Map a task file's ``placement.side`` to the sign used by :func:`place_obstacle`."""
    return _SIDE_SIGNS[side]


def place_obstacle(path: npt.ArrayLike, along: float, clearance: float, side: Side) -> Pose2D:
    """Pose of an obstacle offset laterally from a polyline (docs/06 §3.2).

    The polyline is parametrised by arc length. Exactly at an interior vertex the outgoing segment
    defines the tangent; repeated points (zero-length segments) are ignored.

    Args:
        path: Polyline of shape ``(n, 2)`` in metres, ``n >= 2`` with at least two distinct points.
        along: Fraction of the path length in ``[0, 1]`` (parameter P7).
        clearance: Lateral offset of the obstacle centre from the path [m], ``>= 0`` (P2).
        side: ``+1`` left of the travel direction, ``-1`` right.

    Returns:
        The obstacle centre with ``yaw`` equal to the path heading at that point [rad].

    Raises:
        roboprobe.core.errors.ValidationError: For a malformed path or out-of-range arguments.
    """
    points = _distinct_points(path)
    _check_arguments(along, clearance, side)
    segments = np.diff(points, axis=0)
    lengths = np.linalg.norm(segments, axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(lengths)))
    s = along * cumulative[-1]
    index = int(np.clip(np.searchsorted(cumulative, s, side="right") - 1, 0, len(lengths) - 1))
    tangent = segments[index] / lengths[index]
    on_path = points[index] + tangent * (s - cumulative[index])
    normal = np.array([-tangent[1], tangent[0]])
    centre = on_path + side * clearance * normal
    return Pose2D(x=float(centre[0]), y=float(centre[1]), yaw=math.atan2(tangent[1], tangent[0]))


def _distinct_points(path: npt.ArrayLike) -> npt.NDArray[np.float64]:
    points = np.asarray(path, dtype=np.float64)
    if (
        points.ndim != _POINT_DIM
        or points.shape[1] != _POINT_DIM
        or not np.all(np.isfinite(points))
    ):
        msg = f"path must be a finite (n, 2) array, got shape {points.shape}"
        raise errors.ValidationError(msg, context={"shape": list(points.shape)})
    keep = np.concatenate(([True], np.any(np.diff(points, axis=0) != 0, axis=1)))
    distinct = points[keep]
    if len(distinct) < _POINT_DIM:
        msg = "path needs at least two distinct points"
        raise errors.ValidationError(msg, context={"points": len(points)})
    return distinct


def _check_arguments(along: float, clearance: float, side: int) -> None:
    problems: list[str] = []
    if not 0.0 <= along <= 1.0:
        problems.append(f"along must be in [0, 1], got {along}")
    if not (math.isfinite(clearance) and clearance >= 0.0):
        problems.append(f"clearance must be finite and >= 0, got {clearance}")
    if side not in (-1, 1):
        problems.append(f"side must be -1 or 1, got {side}")
    if problems:
        msg = "; ".join(problems)
        raise errors.ValidationError(msg, context={"problems": list[JsonValue](problems)})
