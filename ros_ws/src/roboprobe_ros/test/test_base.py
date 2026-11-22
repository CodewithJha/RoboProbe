"""Exercise the package in the Jazzy runtime (T-093a)."""

# ruff: noqa: S101

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy.testing as npt
import pytest
import rclpy
from rclpy.context import Context
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSReliabilityPolicy
from roboprobe_ros._vendor.geometry import CircleFootprint
from roboprobe_ros._vendor.geometry.grid import OccupancyGrid
from roboprobe_ros._vendor.perturbation.delay import CommandDelayBuffer
from roboprobe_ros.base import RoboProbeNode

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def ros_context() -> Iterator[Context]:
    """Give each test a private ROS context."""
    context = Context()
    rclpy.init(context=context)
    try:
        yield context
    finally:
        rclpy.shutdown(context=context)


def test_installed_topics_and_vendored_kernels(ros_context: Context) -> None:
    """Installed resources and numerical dependencies resolve without the backend package."""
    node = RoboProbeNode("catalog_check", context=ros_context)
    try:
        assert node.topic("scan_raw").startswith("/")
        assert node.qos("scan_raw").reliability is QoSReliabilityPolicy.BEST_EFFORT
        assert node.qos("cmd_vel").reliability is QoSReliabilityPolicy.RELIABLE
        assert node.qos("amcl_pose").durability is DurabilityPolicy.TRANSIENT_LOCAL
        assert CircleFootprint.__module__.startswith("roboprobe_ros._vendor.")
        assert OccupancyGrid.__module__.startswith("roboprobe_ros._vendor.")
        assert CommandDelayBuffer.__module__.startswith("roboprobe_ros._vendor.")
    finally:
        node.destroy_node()


def test_episode_overrides_and_log(
    ros_context: Context, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two nodes given the same episode seed start with the same random stream."""
    topics = tmp_path / "topics.yaml"
    topics.write_text(
        "topics:\n  scan_raw:\n    name: /sim/scan\n    qos: sensor_data\n", encoding="utf-8"
    )
    perturb = tmp_path / "perturb_params.yaml"
    perturb.write_text("dropout: 0.2\n", encoding="utf-8")
    overrides = [
        Parameter("topics_file", value=str(topics)),
        Parameter("perturb_file", value=str(perturb)),
        Parameter("seed", value=42),
    ]
    first = RoboProbeNode("first_sensor", context=ros_context, parameter_overrides=overrides)
    second = RoboProbeNode("second_sensor", context=ros_context, parameter_overrides=overrides)
    try:
        assert first.topic("scan_raw") == "/sim/scan"
        assert first.perturbation == {"dropout": 0.2}
        npt.assert_array_equal(first.rng.random(4), second.rng.random(4))
        first.log_event("sensor.ready", topic="/sim/scan")
        entry = json.loads(capsys.readouterr().out)
        assert entry["event"] == "sensor.ready"
        assert entry["logger"] == "first_sensor"
        assert entry["topic"] == "/sim/scan"
        assert entry["ts"]
    finally:
        second.destroy_node()
        first.destroy_node()
