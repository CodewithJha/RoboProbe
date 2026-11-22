"""Tests for ``ScenarioSpace.from_yaml`` and the parameter models (T-020b; docs/05 §3, docs/06)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

from roboprobe.core import errors
from roboprobe.core.types import ParamType
from roboprobe.scenario.space import Constraint, ParameterSpec, PriorSpec, ScenarioSpace

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
WAREHOUSE = REPO_ROOT / "configs" / "scenario_spaces" / "warehouse_v1.yaml"
BRANIN = REPO_ROOT / "configs" / "scenario_spaces" / "branin_2d.yaml"
MULTI_MODE = REPO_ROOT / "configs" / "scenario_spaces" / "multi_mode_6d.yaml"
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "spaces"
INVALID = sorted((FIXTURES / "invalid").glob("*.yaml"))
EXPECT_PREFIX = "# expect-path:"


def load_warehouse(text: str | None = None) -> ScenarioSpace:
    if text is None:
        return ScenarioSpace.from_yaml(WAREHOUSE, base_dir=REPO_ROOT)
    return ScenarioSpace.from_text(text, source="edited.yaml", base_dir=REPO_ROOT)


def issue_paths(exc: pytest.ExceptionInfo[errors.ValidationError]) -> list[str]:
    return [issue["path"] for issue in exc.value.context["errors"]]  # type: ignore[index, union-attr]


# --------------------------------------------------------------------------- warehouse_v1


def test_warehouse_space_loads_with_six_enabled_parameters() -> None:
    space = load_warehouse()
    assert space.id == "warehouse_v1"
    assert space.dim == 6
    assert len(space.parameters) == 8
    assert [p.id for p in space.params] == [
        "robot.max_speed", "obstacle.clearance", "env.illuminance",
        "sensor.lidar_noise_std", "env.floor_friction", "comms.cmd_delay_ms",
    ]  # fmt: skip
    assert space.task.id == "warehouse_delivery_v1"
    assert space.task_ref == "tasks/warehouse_delivery_aligned_v1.yaml"
    assert space.oracle_thresholds == "default"
    assert len(space.version) == 12
    assert space.param("env.illuminance").scale == "log"


def test_analytic_benchmark_spaces_load() -> None:
    branin = ScenarioSpace.from_yaml(BRANIN, base_dir=REPO_ROOT)
    multi = ScenarioSpace.from_yaml(MULTI_MODE, base_dir=REPO_ROOT)
    assert branin.id == "branin_2d"
    assert branin.dim == 2
    assert [p.id for p in branin.params] == ["robot.u1", "robot.u2"]
    assert multi.id == "multi_mode_6d"
    assert multi.dim == 6
    assert [p.id for p in multi.params] == [
        "robot.max_speed",
        "obstacle.clearance",
        "env.illuminance",
        "sensor.lidar_noise_std",
        "env.floor_friction",
        "comms.cmd_delay_ms",
    ]


def test_enabling_p7_p8_gives_dim_eight() -> None:
    text = WAREHOUSE.read_text(encoding="utf-8").replace("enabled: false", "enabled: true")
    assert load_warehouse(text).dim == 8


def test_disabled_parameters_are_held_at_nominal() -> None:
    nominal = load_warehouse().nominal_values()
    assert nominal["obstacle.along_path"] == 0.5
    assert nominal["sensor.lidar_dropout"] == 0.0
    assert len(nominal) == 8


def test_version_ignores_comments_and_whitespace() -> None:
    text = WAREHOUSE.read_text(encoding="utf-8")
    edited = "# a new comment\n" + text.replace(
        "name: Max linear speed", "name:   Max linear speed  "
    )
    assert load_warehouse(edited).version == load_warehouse().version


def test_version_changes_with_any_semantic_edit() -> None:
    text = WAREHOUSE.read_text(encoding="utf-8")
    base = load_warehouse().version
    assert load_warehouse(text.replace("high: 0.50", "high: 0.55")).version != base
    assert load_warehouse(text.replace("enabled: false", "enabled: true", 1)).version != base


def test_version_is_stable_across_processes() -> None:
    code = (
        "from pathlib import Path; from roboprobe.scenario.space import ScenarioSpace;"
        f"space = ScenarioSpace.from_yaml(Path({str(WAREHOUSE)!r}),"
        f" base_dir=Path({str(REPO_ROOT)!r}));"
        "print(space.version)"
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter and code
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == load_warehouse().version


def test_task_reference_resolves_against_base_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)
    assert ScenarioSpace.from_yaml(WAREHOUSE).version == load_warehouse().version


def test_strict_task_rejects_provisional_values() -> None:
    legacy = WAREHOUSE.read_text(encoding="utf-8").replace(
        "tasks/warehouse_delivery_aligned_v1.yaml", "tasks/warehouse_delivery_v1.yaml"
    )
    with pytest.raises(errors.ValidationError, match="provisional") as exc:
        ScenarioSpace.from_text(legacy, source="legacy.yaml", base_dir=REPO_ROOT, strict_task=True)
    assert exc.value.code is errors.ErrorCode.SPACE_INVALID
    assert issue_paths(exc) == ["/task"]


def test_unknown_parameter_lookup() -> None:
    with pytest.raises(errors.NotFoundError, match=r"robot\.nope"):
        load_warehouse().param("robot.nope")


def test_unconstrained_space_is_always_feasible() -> None:
    space = load_warehouse()
    assert space.is_feasible(space.nominal_values())


def test_space_is_immutable() -> None:
    space = load_warehouse()
    with pytest.raises(ValueError, match="frozen"):
        space.id = "other"  # type: ignore[misc]


# --------------------------------------------------------------------------- fixtures


def test_valid_mixed_space() -> None:
    space = ScenarioSpace.from_yaml(FIXTURES / "valid" / "mixed.yaml", base_dir=FIXTURES)
    assert space.dim == 5
    assert space.param("env.layout").type is ParamType.CATEGORICAL
    assert space.param("env.people").prior.weights == (4, 3, 2, 1)
    assert space.constraints[0].referenced_ids() == {"env.people", "task.clearance"}


def test_is_feasible_applies_the_constraints() -> None:
    space = ScenarioSpace.from_yaml(FIXTURES / "valid" / "mixed.yaml", base_dir=FIXTURES)
    values = space.nominal_values()
    assert space.is_feasible({**values, "env.people": 3, "task.clearance": 0.5})
    assert not space.is_feasible({**values, "env.people": 3, "task.clearance": 0.2})
    batch = np.array([[3, 0.5], [3, 0.2], [0, 0.0]])
    mask = space.constraint_set().mask(batch, ["env.people", "task.clearance"])
    assert mask.tolist() == [True, False, True]


def test_constraint_reasons_are_reported_per_expression() -> None:
    path = FIXTURES / "invalid" / "constraint_disallowed_call.yaml"
    with pytest.raises(errors.ValidationError, match="only calls to abs, max, min") as exc:
        ScenarioSpace.from_yaml(path, base_dir=FIXTURES)
    assert issue_paths(exc) == ["/constraints/0/expr"]


def expected_path(path: Path) -> str:
    first = path.read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith(EXPECT_PREFIX), f"{path.name} lacks an expect-path header"
    return first.removeprefix(EXPECT_PREFIX).strip()


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.stem)
def test_invalid_fixture_reports_precise_path(path: Path) -> None:
    with pytest.raises(errors.ValidationError) as exc:
        ScenarioSpace.from_yaml(path, base_dir=FIXTURES)
    assert exc.value.code is errors.ErrorCode.SPACE_INVALID
    assert expected_path(path) in issue_paths(exc), exc.value.message


def test_unsafe_tag_is_rejected_not_executed(tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    text = f'id: !!python/object/apply:os.system ["touch {marker}"]\n'
    with pytest.raises(errors.ValidationError, match="YAML error"):
        ScenarioSpace.from_text(text, source="upload", base_dir=FIXTURES)
    assert not marker.exists()


def test_size_limit() -> None:
    text = (FIXTURES / "valid" / "mixed.yaml").read_text(encoding="utf-8")
    with pytest.raises(errors.ValidationError, match="limit is 100"):
        ScenarioSpace.from_text(text, source="upload", base_dir=FIXTURES, max_bytes=100)


def test_all_issues_are_reported_at_once(tmp_path: Path) -> None:
    document = yaml.safe_load((FIXTURES / "valid" / "mixed.yaml").read_text(encoding="utf-8"))
    document["parameters"][0]["nominal"] = 2.0
    document["parameters"][2]["low"] = 0.5
    path = tmp_path / "space.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(errors.ValidationError) as exc:
        ScenarioSpace.from_yaml(path, base_dir=FIXTURES)
    assert issue_paths(exc) == ["/parameters/0/nominal", "/parameters/2/low"]


def test_missing_space_file() -> None:
    with pytest.raises(errors.NotFoundError):
        ScenarioSpace.from_yaml(FIXTURES / "nope.yaml")


# --------------------------------------------------------------------------- models directly


def test_models_validate_on_direct_construction() -> None:
    with pytest.raises(ValueError, match="greater than low"):
        ParameterSpec(
            id="robot.x", name="x", type=ParamType.FLOAT, unit="m", low=1, high=0,
            nominal=0.5, prior=PriorSpec(kind="uniform"), group="robot",
        )  # fmt: skip
    with pytest.raises(ValueError, match="need low and high"):
        ParameterSpec(
            id="robot.x", name="x", type=ParamType.INT, unit="m", nominal=0,
            prior=PriorSpec(kind="uniform"), group="robot",
        )  # fmt: skip
    with pytest.raises(ValueError, match="must be a number"):
        ParameterSpec(
            id="robot.x", name="x", type=ParamType.FLOAT, unit="m", low=0, high=1,
            nominal="a", prior=PriorSpec(kind="uniform"), group="robot",
        )  # fmt: skip
    with pytest.raises(ValueError, match="uniform or discrete"):
        ParameterSpec(
            id="env.c", name="c", type=ParamType.CATEGORICAL, unit="-", choices=("a", "b"),
            nominal="a", prior=PriorSpec(kind="beta", a=1, b=1), group="environment",
        )  # fmt: skip


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"kind": "discrete"}, "positive sum"),
        ({"kind": "discrete", "weights": (0, 0)}, "positive sum"),
        ({"kind": "truncnormal", "mean": 0, "std": 0}, "std > 0"),
        ({"kind": "beta", "a": 1, "b": -1}, "a > 0 and b > 0"),
    ],
)
def test_prior_arguments(kwargs: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        PriorSpec.model_validate(kwargs)


def test_constraint_syntax_error_raised_by_reference_extraction() -> None:
    with pytest.raises(SyntaxError):
        Constraint(expr="a. <").referenced_ids()
