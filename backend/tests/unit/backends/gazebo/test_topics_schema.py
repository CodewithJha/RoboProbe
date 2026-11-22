"""Validate ``topics.yaml`` against ``schemas/ros_topics.schema.json`` (T-091; FR-SIM-003)."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from functools import cache
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from roboprobe.scenario._documents import load_yaml_document
from roboprobe.scenario.task import load_task

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
    names = [topic["name"] for topic in document["topics"].values()]
    assert len(names) == len(set(names))

    task = load_task(REPO_ROOT / "tasks/warehouse_delivery_v1.yaml", strict=False)
    pallet = REPO_ROOT / "ros_ws/src/roboprobe_ros/models/dropped_pallet/model.sdf"
    model = ET.parse(pallet)  # noqa: S314 - checked-in static SDF, not an external input
    size = model.findtext("./model/link/collision/geometry/box/size")
    assert size is not None
    assert tuple(map(float, size.split())) == task.injected_obstacles[0].size
    assert task.injected_obstacles[0].size[-1] == geometry["dropped_pallet_height_m"]


def test_stamped_velocity_and_depth_match_the_actual_bridge_types() -> None:
    document = load_yaml_document(TOPICS_FILE.read_bytes(), source=str(TOPICS_FILE))
    document["stamped_cmd_vel"] = True
    assert not validator().is_valid(document)
    for name in ("cmd_vel_nav", "cmd_vel"):
        document["topics"][name]["type"] = "geometry_msgs/msg/TwistStamped"
    validator().validate(document)
    document["topics"]["depth_points_raw"]["type"] = "sensor_msgs/msg/Image"
    assert not validator().is_valid(document)
