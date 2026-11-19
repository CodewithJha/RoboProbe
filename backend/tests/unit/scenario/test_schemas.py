"""JSON Schema contracts in ``schemas/`` (T-020a; docs/06 §5-§7, docs/12 §3.1, docs/19 §4).

The documentation examples are extracted from the Markdown sources themselves, so a schema/doc
drift fails here rather than in a user's editor.
"""

from __future__ import annotations

import copy
import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
SCHEMAS_DIR = REPO_ROOT / "schemas"
DOCS_DIR = REPO_ROOT / "docs"
FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "schemas"
SCHEMA_NAMES = ("scenario_space", "scenario", "task", "campaign", "experiment")
SCHEMA_BASE_URI = "https://github.com/CodewithJha/RoboProbe/schemas/"


class _NoTimestampLoader(yaml.SafeLoader):
    """Safe YAML loader that keeps timestamps as strings, as JSON Schema expects."""


_NoTimestampLoader.yaml_implicit_resolvers = {
    key: [(tag, regex) for tag, regex in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load_yaml(text: str) -> Any:
    return yaml.load(text, Loader=_NoTimestampLoader)  # noqa: S506 - SafeLoader subclass


@cache
def validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMAS_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def pointer(error: ValidationError) -> str:
    """RFC 6901 JSON pointer of the failing instance location ("" = document root)."""
    return "".join(f"/{part}" for part in error.absolute_path)


def errors(name: str, document: Any) -> list[ValidationError]:
    return list(validator(name).iter_errors(document))


def doc_example(doc: str, heading: str) -> Any:
    """Return the first fenced YAML/JSON block after the heading starting with ``heading``."""
    text = (DOCS_DIR / doc).read_text(encoding="utf-8")
    start = text.index(f"\n{heading}")
    match = re.compile(r"```(yaml|json)\n(.*?)```", re.DOTALL).search(text, start)
    assert match, f"no code block after {heading!r} in {doc}"
    return load_yaml(match.group(2))


DOC_EXAMPLES: dict[str, tuple[str, str, str]] = {
    "space-06-4": ("scenario_space", "06-scenario-parameter-space-and-schema.md", "## 4."),
    "scenario-06-6": ("scenario", "06-scenario-parameter-space-and-schema.md", "## 6."),
    "task-06-7": ("task", "06-scenario-parameter-space-and-schema.md", "## 7."),
    "campaign-12-3.1": ("campaign", "12-api-specification.md", "### 3.1"),
    "experiment-19-4": ("experiment", "19-evaluation-and-experiment-plan.md", "## 4."),
}


def example(key: str) -> Any:
    _, doc, heading = DOC_EXAMPLES[key]
    return doc_example(doc, heading)


# --------------------------------------------------------------------------- schema files


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schema_is_valid_draft_2020_12(name: str) -> None:
    schema = validator(name).schema
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == f"{SCHEMA_BASE_URI}{name}.schema.json"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"] == {"const": 1}


def test_every_schema_file_is_covered() -> None:
    on_disk = {p.name.removesuffix(".schema.json") for p in SCHEMAS_DIR.glob("*.schema.json")}
    assert on_disk == set(SCHEMA_NAMES)


# --------------------------------------------------------------------------- valid documents


@pytest.mark.parametrize("key", DOC_EXAMPLES)
def test_documentation_examples_validate(key: str) -> None:
    name = DOC_EXAMPLES[key][0]
    assert errors(name, example(key)) == []


def test_strategy_config_example_from_doc_07_validates_inside_a_campaign() -> None:
    fragment = doc_example("07-intelligent-test-selection-algorithms.md", "## 10.")
    campaign = {"space": {"id": "warehouse_v1"}, "backend": "kinematic2d", "budget": 10} | fragment
    assert errors("campaign", campaign) == []


@pytest.mark.parametrize(
    "path", sorted((FIXTURES_DIR / "valid").glob("*.yaml")), ids=lambda p: p.stem
)
def test_valid_fixtures_validate(path: Path) -> None:
    name = path.stem.split("__")[0]
    assert errors(name, load_yaml(path.read_text(encoding="utf-8"))) == []


def test_task_schema_accepts_tbd_placeholders_for_the_loader_guard() -> None:
    task = example("task-06-7")
    assert task["goal"]["x"] == "TBD_T092"
    assert errors("task", task) == []


# --------------------------------------------------------------------------- invalid documents


@pytest.mark.parametrize(
    "path", sorted((FIXTURES_DIR / "invalid").glob("*.yaml")), ids=lambda p: p.stem
)
def test_invalid_fixtures_fail_at_expected_pointer(path: Path) -> None:
    case = load_yaml(path.read_text(encoding="utf-8"))
    found = {pointer(e) for e in errors(case["schema"], case["document"])}
    assert case["pointer"] in found, f"expected an error at {case['pointer']!r}, got {found}"


def _required_removal_cases() -> list[tuple[str, str, tuple[str | int, ...], str]]:
    """(example key, schema name, path to object, required field) for every required field."""
    nested: dict[str, list[tuple[str | int, ...]]] = {
        "space-06-4": [(), ("parameters", 0), ("parameters", 0, "prior")],
        "scenario-06-6": [(), ("space",), ("expect",)],
        "task-06-7": [
            (),
            ("start",),
            ("goal_tolerance",),
            ("time_limit",),
            ("injected_obstacles", 0),
            ("injected_obstacles", 0, "placement"),
        ],
        "campaign-12-3.1": [(), ("space",), ("strategy",)],
        "experiment-19-4": [(), ("seeds",), ("strategies", 0)],
    }
    cases = []
    for key, paths in nested.items():
        name = DOC_EXAMPLES[key][0]
        for obj_path in paths:
            subschema = _subschema(validator(name).schema, obj_path)
            cases.extend((key, name, obj_path, field) for field in subschema["required"])
    return cases


def _subschema(schema: dict[str, Any], path: tuple[str | int, ...]) -> dict[str, Any]:
    node = schema
    for part in path:
        node = node["items"] if isinstance(part, int) else node["properties"][part]
        while "$ref" in node:
            node = schema["$defs"][node["$ref"].removeprefix("#/$defs/")]
    return node


@pytest.mark.parametrize(
    ("key", "name", "obj_path", "field"),
    _required_removal_cases(),
    ids=lambda v: "/".join(map(str, v)) if isinstance(v, tuple) else str(v),
)
def test_removing_a_required_field_fails_with_json_pointer(
    key: str, name: str, obj_path: tuple[str | int, ...], field: str
) -> None:
    document = copy.deepcopy(example(key))
    target = document
    for part in obj_path:
        target = target[part]
    del target[field]
    expected = "".join(f"/{part}" for part in obj_path)
    required_errors = [e for e in errors(name, document) if e.validator == "required"]
    assert any(pointer(e) == expected and repr(field) in e.message for e in required_errors)


def test_missing_parameter_type_reports_only_that_error() -> None:
    space = copy.deepcopy(example("space-06-4"))
    del space["parameters"][0]["type"]
    messages = [e.message for e in errors("scenario_space", space)]
    assert messages == ["'type' is a required property"]


@pytest.mark.parametrize("key", DOC_EXAMPLES)
def test_unknown_top_level_keys_are_rejected(key: str) -> None:
    document = example(key) | {"unexpected": True}
    found = [
        e for e in errors(DOC_EXAMPLES[key][0], document) if e.validator == "additionalProperties"
    ]
    assert found
    assert pointer(found[0]) == ""
