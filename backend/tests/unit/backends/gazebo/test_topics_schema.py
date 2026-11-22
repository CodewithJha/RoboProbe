"""Validate ``topics.yaml`` against ``schemas/ros_topics.schema.json`` (T-091; FR-SIM-003)."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from roboprobe.scenario._documents import load_yaml_document

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[5]
TOPICS_FILE = REPO_ROOT / "ros_ws/src/roboprobe_ros/config/topics.yaml"
SCHEMA_FILE = REPO_ROOT / "schemas/ros_topics.schema.json"


@cache
def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def test_topics_yaml_matches_schema() -> None:
    """Committed topics map validates and pallet stays below the lidar plane.

    Implements: FR-SIM-003, T-091.
    """
    document = load_yaml_document(TOPICS_FILE.read_bytes(), source=str(TOPICS_FILE))
    errors = list(validator().iter_errors(document))
    assert not errors, [error.message for error in errors]

    geometry = document["geometry"]
    margin = geometry["lidar_plane_height_m"] - geometry["dropped_pallet_height_m"]
    assert margin >= 0.05, "pallet top must sit at least 5 cm below the lidar plane (OQ-2)"
