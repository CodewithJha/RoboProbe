"""Tests for SUT profile loading and hashing (T-016; docs/10 §4, docs/11 ``sut_profiles``)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator

from roboprobe.core import errors
from roboprobe.core.settings import BackendsSettings
from roboprobe.core.types import SutProfile
from roboprobe.scenario import _documents, sut_profile
from roboprobe.scenario.sut_profile import PROFILE_CONFIGS, config_hash, load_sut_profile

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
PROFILES_DIR = REPO_ROOT / "configs" / "sut_profiles"
SCHEMA_FILE = REPO_ROOT / "schemas" / "sut_profile.schema.json"


def k2d_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": 1,
        "id": "k2d_test",
        "backend": "kinematic2d",
        "config": {
            "model_file": "configs/backends/kinematic2d_v1.yaml",
            "gain_overrides": {"controller.lookahead_m": 0.8},
        },
    }
    return document | overrides


def nav2_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": 1,
        "id": "nav2_test",
        "backend": "gazebo_nav2",
        "config": {
            "base_nav2_params": "nav2_bringup/params/nav2_params.yaml",
            "speed_param_paths": ["velocity_smoother.ros__parameters.max_velocity[0]"],
            "nav2_overrides": {
                "controller_server": {"ros__parameters": {"controller_frequency": 20.0}}
            },
        },
    }
    return document | overrides


def write(tmp_path: Path, document: dict[str, Any] | str, name: str | None = None) -> Path:
    if isinstance(document, dict):
        name = name or f"{document['id']}.yaml"
        text = yaml.safe_dump(document, sort_keys=False)
    else:
        text = document
    path = tmp_path / (name or "profile.yaml")
    path.write_text(text, encoding="utf-8")
    return path


def error_paths(exc: pytest.ExceptionInfo[errors.ValidationError]) -> list[str]:
    found = exc.value.context["errors"]
    assert isinstance(found, list)
    return [str(e["path"]) for e in found if isinstance(e, dict)]


@pytest.mark.parametrize("path", sorted(PROFILES_DIR.glob("*.yaml")), ids=lambda p: p.stem)
def test_shipped_profiles_load(path: Path) -> None:
    profile = load_sut_profile(path)
    assert isinstance(profile, SutProfile)
    assert profile.id == path.stem
    assert len(profile.config_hash) == 64


def test_shipped_defaults_exist() -> None:
    assert {p.stem for p in PROFILES_DIR.glob("*.yaml")} >= {
        "benchmark_default",
        "k2d_default",
        "tb4_nav2_default",
    }


def test_k2d_profile_is_normalised(tmp_path: Path) -> None:
    profile = load_sut_profile(write(tmp_path, k2d_document()))
    assert profile.backend == "kinematic2d"
    assert profile.config == {
        "model_file": "configs/backends/kinematic2d_v1.yaml",
        "gain_overrides": {"controller.lookahead_m": 0.8},
    }


def test_defaults_are_filled_in(tmp_path: Path) -> None:
    document = k2d_document(config={"model_file": "configs/backends/kinematic2d_v1.yaml"})
    profile = load_sut_profile(write(tmp_path, document))
    assert profile.config["gain_overrides"] == {}


def test_nav2_profile_loads(tmp_path: Path) -> None:
    profile = load_sut_profile(write(tmp_path, nav2_document()))
    assert profile.config["speed_param_paths"] == [
        "velocity_smoother.ros__parameters.max_velocity[0]"
    ]


def test_hash_is_stable_across_formatting_and_metadata(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    first = load_sut_profile(write(tmp_path / "a", k2d_document()))
    reordered = k2d_document(name="Pretty name", description="docs only")
    reordered["config"] = dict(reversed(list(reordered["config"].items())))
    text = "# comment\n" + yaml.safe_dump(reordered, sort_keys=True, indent=4)
    second = load_sut_profile(write(tmp_path, text, "k2d_test.yaml"))
    assert first.config_hash == second.config_hash


def test_hash_changes_with_behaviour(tmp_path: Path) -> None:
    base = load_sut_profile(write(tmp_path, k2d_document()))
    changed = k2d_document()
    changed["config"]["gain_overrides"] = {"controller.lookahead_m": 0.9}
    other = load_sut_profile(write(tmp_path, changed))
    assert base.config_hash != other.config_hash


def test_config_hash_known_value() -> None:
    payload = '{"backend":"kinematic2d","config":{"a":1,"b":[0.1,true]}}'
    expected = hashlib.sha256(payload.encode()).hexdigest()
    assert config_hash("kinematic2d", {"b": [0.1, True], "a": 1}) == expected


def test_config_hash_rounds_floats_like_space_version() -> None:
    assert config_hash("kinematic2d", {"v": 0.1 + 0.2}) == config_hash("kinematic2d", {"v": 0.3})


def test_unknown_backend_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(errors.ValidationError) as exc:
        load_sut_profile(write(tmp_path, k2d_document(backend="webots")))
    assert "/backend" in error_paths(exc)


def test_backend_without_config_model_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sut_profile, "PROFILE_CONFIGS", {})
    with pytest.raises(errors.ValidationError) as exc:
        load_sut_profile(write(tmp_path, k2d_document()))
    assert error_paths(exc) == ["/backend"]


@pytest.mark.parametrize(
    ("config", "pointer"),
    [
        ({"gain_overrides": {}}, "/config"),
        ({"model_file": "/etc/passwd"}, "/config/model_file"),
        ({"model_file": "configs/../../secret.yaml"}, "/config/model_file"),
        ({"model_file": "m.yaml", "gain_overrides": {"bad key": 1}}, "/config/gain_overrides"),
        ({"model_file": "m.yaml", "gain_overrides": {"a": [1]}}, "/config/gain_overrides/a"),
        ({"model_file": "m.yaml", "extra": 1}, "/config"),
    ],
)
def test_invalid_k2d_config(tmp_path: Path, config: dict[str, Any], pointer: str) -> None:
    with pytest.raises(errors.ValidationError) as exc:
        load_sut_profile(write(tmp_path, k2d_document(config=config)))
    assert pointer in error_paths(exc)


@pytest.mark.parametrize(
    ("speed_param_paths", "pointer"),
    [
        ([], "/config/speed_param_paths"),
        (["a.b", "a.b"], "/config/speed_param_paths"),
        (["a..b"], "/config/speed_param_paths/0"),
        (["a.b[x]"], "/config/speed_param_paths/0"),
    ],
)
def test_invalid_speed_param_paths(
    tmp_path: Path, speed_param_paths: list[str], pointer: str
) -> None:
    document = nav2_document()
    document["config"]["speed_param_paths"] = speed_param_paths
    with pytest.raises(errors.ValidationError) as exc:
        load_sut_profile(write(tmp_path, document))
    assert pointer in error_paths(exc)


def test_model_errors_are_reported_under_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bypass the schema to prove the typed model is a second line of defence.
    monkeypatch.setattr(_documents, "schema_validator", _permissive_validator)
    document = k2d_document(config={"model_file": ""})
    with pytest.raises(errors.ValidationError) as exc:
        load_sut_profile(write(tmp_path, document))
    assert error_paths(exc) == ["/config/model_file"]


def _permissive_validator(_name: str) -> Draft202012Validator:
    return Draft202012Validator({})


def test_id_must_match_file_name(tmp_path: Path) -> None:
    with pytest.raises(errors.ValidationError) as exc:
        load_sut_profile(write(tmp_path, k2d_document(), "other_name.yaml"))
    assert error_paths(exc) == ["/id"]


def test_provisional_rejected_only_when_strict(tmp_path: Path) -> None:
    path = write(tmp_path, nav2_document(provisional=["speed_param_paths"]))
    assert load_sut_profile(path).id == "nav2_test"
    with pytest.raises(errors.ValidationError) as exc:
        load_sut_profile(path, strict=True)
    assert error_paths(exc) == ["/provisional/0"]


def test_shipped_nav2_profile_speed_paths_verified_t091() -> None:
    profile = load_sut_profile(PROFILES_DIR / "tb4_nav2_default.yaml", strict=True)
    assert profile.id == "tb4_nav2_default"
    tuned = load_sut_profile(PROFILES_DIR / "tb4_nav2_tuned.yaml", strict=True)
    assert tuned.id == "tb4_nav2_tuned"
    assert tuned.config_hash != profile.config_hash
    assert load_sut_profile(PROFILES_DIR / "k2d_default.yaml", strict=True).id == "k2d_default"


def test_unknown_provisional_key(tmp_path: Path) -> None:
    with pytest.raises(errors.ValidationError) as exc:
        load_sut_profile(write(tmp_path, nav2_document(provisional=["model_file"])))
    assert error_paths(exc) == ["/provisional/0"]


def test_missing_file() -> None:
    with pytest.raises(errors.NotFoundError):
        load_sut_profile(Path("does/not/exist.yaml"))


def test_yaml_errors_are_validation_errors(tmp_path: Path) -> None:
    with pytest.raises(errors.ValidationError):
        load_sut_profile(write(tmp_path, "id: a\nid: b\n", "a.yaml"))


def test_supported_backends_agree_with_schema_and_settings() -> None:
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    enum = set(schema["properties"]["backend"]["enum"])
    conditional = {branch["if"]["properties"]["backend"]["const"] for branch in schema["allOf"]}
    assert enum == conditional == set(PROFILE_CONFIGS)
    assert enum - {"benchmark"} == set(BackendsSettings.model_fields)
