"""Regression scenario export/import (T-026; docs/06 §6)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
import yaml
from jsonschema import Draft202012Validator

from roboprobe.core import errors
from roboprobe.core.types import Verdict
from roboprobe.scenario.hashing import scenario_hash
from roboprobe.scenario.regression import (
    EXPORT_KEY_ORDER,
    RegressionExpect,
    RegressionProvenance,
    export_regression,
    load_regression,
)
from roboprobe.scenario.space import ScenarioSpace

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
WAREHOUSE = REPO_ROOT / "configs" / "scenario_spaces" / "warehouse_v1.yaml"
SCHEMA = REPO_ROOT / "schemas" / "scenario.schema.json"
SEED = 1_849_302_231
SOURCE_RUN = UUID("7c1e7e0e-3b0f-4b77-9a54-1f0e4f5d2b11")


def warehouse() -> ScenarioSpace:
    return ScenarioSpace.from_yaml(WAREHOUSE, base_dir=REPO_ROOT)


def exported() -> tuple[str, object]:
    space = warehouse()
    scenario = space.make_scenario(
        {
            "robot.max_speed": 0.44,
            "obstacle.clearance": 0.31,
            "env.illuminance": 12.5,
            "sensor.lidar_noise_std": 0.062,
            "env.floor_friction": 0.72,
            "comms.cmd_delay_ms": 140,
        }
    )
    text = export_regression(
        scenario,
        SEED,
        RegressionProvenance(
            source_run=SOURCE_RUN,
            failure_mode='FM-03 "dark-fast-noisy collision"',
            exported_at=datetime(2026, 11, 19, 18, 30, tzinfo=UTC),
        ),
        RegressionExpect(verdict=Verdict.PASS),
    )
    return text, scenario


def test_round_trip_preserves_scenario_hash(tmp_path: Path) -> None:
    text, original = exported()
    path = tmp_path / "fail.yaml"
    path.write_text(text, encoding="utf-8")
    loaded = load_regression(path, space=warehouse())
    assert loaded.scenario.scenario_hash == original.scenario_hash
    assert loaded.scenario == original
    assert loaded.seed == SEED
    assert loaded.expect is not None
    assert loaded.expect.verdict is Verdict.PASS


def test_exported_file_validates_against_schema() -> None:
    text, _ = exported()
    document = yaml.safe_load(text)
    Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).validate(document)
    assert list(document) == [k for k in EXPORT_KEY_ORDER if k in document]


def test_space_version_mismatch_suggests_upgrade(tmp_path: Path) -> None:
    text, _ = exported()
    document = yaml.safe_load(text)
    document["space"]["version"] = "aaaaaaaaaaaa"
    path = tmp_path / "old.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(errors.ValidationError, match="space upgrade") as exc:
        load_regression(path, space=warehouse())
    assert "aaaaaaaaaaaa" in str(exc.value)


def test_load_without_space_rebuilds_hash(tmp_path: Path) -> None:
    text, original = exported()
    path = tmp_path / "s.yaml"
    path.write_text(text, encoding="utf-8")
    loaded = load_regression(path)
    assert loaded.scenario.scenario_hash == scenario_hash(original.space_version, original.values)
