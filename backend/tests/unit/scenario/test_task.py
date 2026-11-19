"""Tests for the task loader, time limit and TBD guard (T-027; docs/06 §1, §7)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from roboprobe.core import errors
from roboprobe.core.types import Pose2D, TaskSpec
from roboprobe.scenario import _documents
from roboprobe.scenario.task import (
    find_placeholders,
    load_nominal_path,
    load_task,
    polyline_length_m,
    time_limit_s,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
WAREHOUSE_TASK = REPO_ROOT / "tasks" / "warehouse_delivery_v1.yaml"
CHECK_SCRIPT = REPO_ROOT / "scripts" / "check_no_tbd.py"


def task_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": 1,
        "id": "corridor_v1",
        "world": {"kinematic2d": "worlds/corridor.json"},
        "map": "maps/corridor.yaml",
        "start": {"x": 0.0, "y": 0.0, "yaw": 0.0},
        "goal": {"x": 10.0, "y": 0.0, "yaw": 0.0},
        "goal_tolerance": {"xy": 0.25, "yaw": 0.5},
        "nominal_path": "paths/corridor.csv",
        "time_limit": {"factor": 2.5, "offset_s": 10, "cap_s": 120},
    }
    return document | overrides


def write_task(tmp_path: Path, document: dict[str, Any] | str, csv: str | None = None) -> Path:
    path = tmp_path / "task.yaml"
    text = document if isinstance(document, str) else yaml.safe_dump(document, sort_keys=False)
    path.write_text(text, encoding="utf-8")
    if csv is not None:
        (tmp_path / "paths").mkdir(exist_ok=True)
        (tmp_path / "paths" / "corridor.csv").write_text(csv, encoding="utf-8")
    return path


def issue_paths(exc: pytest.ExceptionInfo[errors.ValidationError]) -> list[str]:
    return [issue["path"] for issue in exc.value.context["errors"]]  # type: ignore[index, union-attr]


# --------------------------------------------------------------------------- shipped task


def test_warehouse_task_loads_non_strict() -> None:
    task = load_task(WAREHOUSE_TASK, strict=False)
    assert task.id == "warehouse_delivery_v1"
    assert task.start == Pose2D(x=2.12, y=-21.3, yaw=1.57)
    assert task.time_limit.cap_s == 120
    assert task.injected_obstacles[0].placement.along == "obstacle.along_path"
    assert set(task.provisional) == {"goal", "nominal_path", "injected_obstacles"}


def test_warehouse_task_is_rejected_in_strict_mode_while_provisional() -> None:
    with pytest.raises(errors.ValidationError, match="provisional") as exc:
        load_task(WAREHOUSE_TASK, strict=True)
    assert issue_paths(exc) == ["/goal", "/nominal_path", "/injected_obstacles"]


def test_warehouse_nominal_path_matches_task() -> None:
    task = load_task(WAREHOUSE_TASK, strict=False)
    points = load_nominal_path(WAREHOUSE_TASK, task)
    assert points.shape[1] == 2
    length = polyline_length_m(points)
    assert 12.0 <= length <= 15.0  # docs/06 §1: goal ~12-15 m from Dock A


# --------------------------------------------------------------------------- loader errors


def test_placeholders_rejected_in_both_modes_with_pointer(tmp_path: Path) -> None:
    document = task_document(goal={"x": "TBD_T092", "y": "TBD_T092", "yaw": 1.57})
    path = write_task(tmp_path, document)
    for strict in (False, True):
        with pytest.raises(errors.ValidationError, match="TBD_T092") as exc:
            load_task(path, strict=strict)
        assert issue_paths(exc) == ["/goal/x", "/goal/y"]
        assert "backlog task T092" in str(exc.value)


def test_doc_06_example_is_rejected_because_of_placeholders(tmp_path: Path) -> None:
    text = (REPO_ROOT / "docs" / "06-scenario-parameter-space-and-schema.md").read_text("utf-8")
    block = text.split("## 7.", 1)[1].split("```yaml\n", 1)[1].split("```", 1)[0]
    with pytest.raises(errors.ValidationError) as exc:
        load_task(write_task(tmp_path, block), strict=False)
    assert issue_paths(exc) == ["/goal/x", "/goal/y", "/injected_obstacles/0/size/2"]


def test_schema_violation_reports_pointer(tmp_path: Path) -> None:
    path = write_task(tmp_path, task_document(goal_tolerance={"xy": 0.25}))
    with pytest.raises(errors.ValidationError) as exc:
        load_task(path, strict=False)
    assert exc.value.code is errors.ErrorCode.VALIDATION_ERROR
    assert issue_paths(exc) == ["/goal_tolerance"]


def test_missing_file_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(errors.NotFoundError):
        load_task(tmp_path / "missing.yaml", strict=False)


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("id: a\nid: b\n", "duplicate key 'id'"),
        ("!!python/object/apply:os.system ['true']\n", "YAML error"),
        ("a: [1, 2\n", "line 2"),
    ],
)
def test_unsafe_or_malformed_yaml_rejected(tmp_path: Path, text: str, match: str) -> None:
    with pytest.raises(errors.ValidationError, match=match):
        load_task(write_task(tmp_path, text), strict=False)


def test_model_errors_are_reported_with_pointer(tmp_path: Path) -> None:
    # Valid for the schema (yaw unconstrained there) but NaN is rejected by the model.
    path = write_task(tmp_path, task_document(start={"x": 0.0, "y": 0.0, "yaw": float("nan")}))
    with pytest.raises(errors.ValidationError) as exc:
        load_task(path, strict=False)
    assert issue_paths(exc) == ["/start/yaw"]


def test_document_size_limit_and_timestamps_kept_as_strings() -> None:
    with pytest.raises(errors.ValidationError, match="limit is 4"):
        _documents.load_yaml_document("a: 1234", source="<upload>", max_bytes=4)
    assert _documents.load_yaml_document("t: 2026-11-19T18:30:00Z", source="x") == {
        "t": "2026-11-19T18:30:00Z"
    }


def test_json_pointer_escapes_rfc_6901() -> None:
    assert _documents.json_pointer(["a/b", "c~d", 0]) == "/a~1b/c~0d/0"
    assert _documents.json_pointer([]) == ""


def test_find_placeholders_walks_nested_documents() -> None:
    document = {"a": ["TBD_T091", {"b": "TBD_T092"}], "c": "TBD", "d": 1}
    assert find_placeholders(document) == [("/a/0", "TBD_T091"), ("/a/1/b", "TBD_T092")]


# --------------------------------------------------------------------------- nominal path

CSV_OK = "x,y\n0.0,0.0\n5.0,0.0\n10.0,0.1\n"


def test_load_nominal_path(tmp_path: Path) -> None:
    path = write_task(tmp_path, task_document(), csv=CSV_OK)
    points = load_nominal_path(path, load_task(path, strict=True))
    assert points.shape == (3, 2)
    assert polyline_length_m(points) == pytest.approx(5.0 + np.hypot(5.0, 0.1))


@pytest.mark.parametrize(
    ("csv", "match"),
    [
        ("x,y\n0.0,0.0\n", ">= 2 rows"),
        ("x,y,z\n0,0,0\n10,0,0\n", ">= 2 rows"),
        ("x,y\n0.0,0.0\nfoo,1\n", "numeric"),
        ("x,y\n0.0,0.0\nnan,0\n10,0\n", "finite"),
        ("x,y\n1.0,0.0\n10.0,0.0\n", "from the start"),
        ("x,y\n0.0,0.0\n9.0,0.0\n", "from the goal"),
    ],
)
def test_nominal_path_validation(tmp_path: Path, csv: str, match: str) -> None:
    path = write_task(tmp_path, task_document(), csv=csv)
    with pytest.raises(errors.ValidationError, match=match):
        load_nominal_path(path, load_task(path, strict=False))


def test_nominal_path_must_stay_in_task_directory(tmp_path: Path) -> None:
    path = write_task(tmp_path, task_document(nominal_path="../outside.csv"))
    with pytest.raises(errors.ValidationError, match="inside the task directory"):
        load_nominal_path(path, load_task(path, strict=False))


def test_nominal_path_missing_file(tmp_path: Path) -> None:
    path = write_task(tmp_path, task_document())
    with pytest.raises(errors.NotFoundError):
        load_nominal_path(path, load_task(path, strict=False))


# --------------------------------------------------------------------------- time limit


@pytest.fixture
def task() -> TaskSpec:
    return TaskSpec.model_validate(task_document())


@pytest.mark.parametrize(
    ("max_speed", "length", "expected"),
    [
        (0.5, 13.0, 2.5 * 13.0 / 0.5 + 10),  # 75 s
        (0.26, 13.0, 120.0),  # 2.5*13/0.26+10 = 135 s -> capped
        (0.5, 0.0, 10.0),
    ],
)
def test_time_limit_formula_and_cap(
    task: TaskSpec, max_speed: float, length: float, expected: float
) -> None:
    assert time_limit_s(task, max_speed, length) == pytest.approx(expected)


@pytest.mark.parametrize(("max_speed", "length"), [(0.0, 1.0), (-1.0, 1.0), (0.5, -1.0)])
def test_time_limit_rejects_invalid_inputs(task: TaskSpec, max_speed: float, length: float) -> None:
    with pytest.raises(ValueError, match="must be"):
        time_limit_s(task, max_speed, length)


# --------------------------------------------------------------------------- check_no_tbd.py


def run_check(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed interpreter and script
        [sys.executable, str(CHECK_SCRIPT), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_script_passes_on_repository_tasks() -> None:
    result = run_check(REPO_ROOT / "tasks")
    assert result.returncode == 0, result.stderr


def test_check_script_strict_flags_provisional() -> None:
    result = run_check("--strict", WAREHOUSE_TASK)
    assert result.returncode == 1
    assert "provisional" in result.stderr


def test_check_script_finds_placeholders_and_bad_yaml(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text("goal: {x: TBD_T092}\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("TBD_T092", encoding="utf-8")
    result = run_check(tmp_path)
    assert result.returncode == 1
    assert "/goal/x: placeholder TBD_T092" in result.stderr
    assert "notes.txt" not in result.stderr
    (tmp_path / "b.yml").write_text("a: [\n", encoding="utf-8")
    assert run_check(tmp_path).returncode == 2


def test_schemas_are_read_from_the_installed_package_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "schemas").mkdir()
    packaged = tmp_path / "schemas" / "task.schema.json"
    packaged.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(_documents.resources, "files", lambda _pkg: tmp_path)
    assert _documents._schema_file("task") == packaged
