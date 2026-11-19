"""Task file loader and episode time limit (docs/06 §1, §7).

A task file describes the navigation task under test: start and goal poses, tolerances, the nominal
path polyline and the obstacles injected along it. Values that later Gazebo tasks will determine are
written as ``TBD_Tnnn`` placeholders (e.g. ``TBD_T092``); they can never be loaded. Values that are
already usable but await verification are listed under ``provisional`` and are rejected only when
``strict=True`` (release builds, Gazebo runs).

Implements: FR-SCN-001
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pydantic

from roboprobe.core.types import TaskSpec
from roboprobe.scenario._documents import (
    document_error,
    json_pointer,
    load_yaml_document,
    read_document,
    validate_document,
)

__all__ = [
    "PLACEHOLDER_PATTERN",
    "find_placeholders",
    "load_nominal_path",
    "load_task",
    "polyline_length_m",
    "time_limit_s",
]

_PLACEHOLDER_PREFIX = "TBD_T"
PLACEHOLDER_PATTERN = re.compile(rf"^{_PLACEHOLDER_PREFIX}\d{{3}}$")
"""A value to be fixed by the named backlog task, e.g. ``TBD_T092``."""

_TASK_SCHEMA = "task"
_PATH_DIM = 2
_MIN_PATH_POINTS = 2
_PATH_HEADER = "x,y"


def find_placeholders(document: object, pointer: str = "") -> list[tuple[str, str]]:
    """Return ``(json_pointer, placeholder)`` for every ``TBD_Tnnn`` value in ``document``."""
    if isinstance(document, str):
        return [(pointer, document)] if PLACEHOLDER_PATTERN.match(document) else []
    children: list[tuple[str | int, object]]
    if isinstance(document, dict):
        children = list(document.items())
    elif isinstance(document, list):
        children = list(enumerate(document))
    else:
        return []
    found: list[tuple[str, str]] = []
    for key, value in children:
        found.extend(find_placeholders(value, pointer + json_pointer([key])))
    return found


def _backlog_task(placeholder: str) -> str:
    """``"TBD_T092"`` -> ``"T-092"`` (backlog task id, docs/22)."""
    return f"T-{placeholder.removeprefix(_PLACEHOLDER_PREFIX)}"


def load_task(path: Path, *, strict: bool) -> TaskSpec:
    """Load and validate a task file.

    Args:
        path: Task YAML file.
        strict: Also reject values listed under ``provisional``.

    Returns:
        The validated task.

    Raises:
        roboprobe.core.errors.NotFoundError: If the file does not exist.
        roboprobe.core.errors.ValidationError: On YAML, schema or model errors, any ``TBD_Tnnn``
            placeholder, or (strict) provisional values; ``context["errors"]`` lists JSON pointers.
    """
    source = str(path)
    document = load_yaml_document(read_document(path), source=source)
    validate_document(document, schema=_TASK_SCHEMA, source=source)
    placeholders = find_placeholders(document)
    if placeholders:
        raise document_error(
            source,
            [
                (p, f"unresolved placeholder {v}; it is filled by backlog task {_backlog_task(v)}")
                for p, v in placeholders
            ],
        )
    try:
        task = TaskSpec.model_validate(document)
    except pydantic.ValidationError as exc:
        raise document_error(
            source, [(json_pointer(e["loc"]), e["msg"]) for e in exc.errors()]
        ) from exc
    if strict and task.provisional:
        raise document_error(
            source,
            [
                (f"/{name}", "provisional value is not allowed in strict mode")
                for name in task.provisional
            ],
        )
    return task


def load_nominal_path(task_file: Path, task: TaskSpec) -> npt.NDArray[np.float64]:
    """Load the task's nominal path polyline (CSV with header ``x,y``), relative to the task file.

    The path must stay inside the task file's directory, have at least two finite points, and
    start/end within ``goal_tolerance.xy`` of the start and goal positions.

    Returns:
        Array of shape ``(n, 2)``: x, y in metres.

    Raises:
        roboprobe.core.errors.NotFoundError: If the CSV does not exist.
        roboprobe.core.errors.ValidationError: On an escaping path or malformed/inconsistent data.
    """
    base = task_file.resolve().parent
    csv_path = (base / task.nominal_path).resolve()
    source = str(csv_path)
    if not csv_path.is_relative_to(base):
        raise document_error(
            str(task_file), [("/nominal_path", "must stay inside the task directory")]
        )
    lines = read_document(csv_path).decode("utf-8").splitlines()
    if not lines or lines[0].strip() != _PATH_HEADER:
        raise document_error(source, [("", f"first line must be the header {_PATH_HEADER!r}")])
    rows = [line for line in lines[1:] if line.strip()]
    if len(rows) < _MIN_PATH_POINTS:
        raise document_error(source, [("", f"expected >= {_MIN_PATH_POINTS} rows of x,y")])
    try:
        points = np.loadtxt(rows, delimiter=",", ndmin=2, dtype=np.float64)
    except ValueError as exc:
        raise document_error(source, [("", f"not a numeric x,y CSV: {exc}")]) from exc
    if points.shape[1] != _PATH_DIM or points.shape[0] < _MIN_PATH_POINTS:
        raise document_error(
            source, [("", f"expected >= {_MIN_PATH_POINTS} rows of x,y; got shape {points.shape}")]
        )
    if not np.all(np.isfinite(points)):
        raise document_error(source, [("", "coordinates must be finite")])
    tolerance = task.goal_tolerance.xy
    for label, row, pose in (("first", 0, task.start), ("last", -1, task.goal)):
        gap = math.dist(points[row], (pose.x, pose.y))
        if gap > tolerance:
            target = "start" if row == 0 else "goal"
            raise document_error(
                source, [("", f"{label} point is {gap:.3f} m from the {target} (> {tolerance} m)")]
            )
    return points


def polyline_length_m(points: npt.NDArray[np.float64]) -> float:
    """Total length of a polyline of shape ``(n, 2)`` [m]."""
    return float(np.sum(np.linalg.norm(np.diff(points, axis=0), axis=1)))


def time_limit_s(task: TaskSpec, max_speed_mps: float, path_length_m: float) -> float:
    """Episode time limit ``T_max = min(cap_s, factor * L / v_max + offset_s)`` (docs/06 §1).

    Args:
        task: The task (provides ``time_limit``).
        max_speed_mps: Robot max linear speed for this scenario (parameter P1) [m/s].
        path_length_m: Nominal path length ``L`` [m].

    Raises:
        ValueError: If ``max_speed_mps`` is not positive or ``path_length_m`` is negative.
    """
    if not max_speed_mps > 0:
        msg = f"max_speed_mps must be > 0, got {max_speed_mps}"
        raise ValueError(msg)
    if not path_length_m >= 0:
        msg = f"path_length_m must be >= 0, got {path_length_m}"
        raise ValueError(msg)
    spec = task.time_limit
    return min(spec.cap_s, spec.factor * path_length_m / max_speed_mps + spec.offset_s)
