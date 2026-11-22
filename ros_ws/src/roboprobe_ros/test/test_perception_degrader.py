"""Test the Jazzy point-cloud relay against the configured model (T-093c)."""

# ruff: noqa: S101

from __future__ import annotations

import json
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING

import numpy as np
import numpy.testing as npt
import pytest
import rclpy
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import QoSProfile, QoSReliabilityPolicy
from roboprobe_ros._vendor.perturbation.perception import PerceptionModel
from roboprobe_ros.perception_degrader import PerceptionDegrader, main
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2
from std_msgs.msg import Header

if TYPE_CHECKING:
    from collections.abc import Iterator

_MODEL = Path(__file__).resolve().parents[4] / "configs/perception/oakd_lowlight_v1.yaml"
_INPUT = "/test/depth_raw"
_OUTPUT = "/test/depth"
_LUX_LEVELS = (5.0, 50.0, 500.0)
_DEPTH = 1
_SIZE = 320 * 240
_CAMERA_PERIOD_MS = 100.0
_SEED = 303


@pytest.fixture
def ros_context() -> Iterator[Context]:
    """Start and stop an isolated ROS context."""
    context = Context()
    rclpy.init(context=context)
    try:
        yield context
    finally:
        rclpy.shutdown(context=context)


def _write_parameters(path: Path, lux: float, output: str = _OUTPUT) -> list[Parameter]:
    topics = path / "topics.yaml"
    perturb = path / "perturb_params.yaml"
    topics.write_text(
        f"topics:\n"
        f"  depth_points_raw: {{name: {_INPUT}, qos: sensor_data}}\n"
        f"  depth_points: {{name: {output}, qos: sensor_data}}\n",
        encoding="utf-8",
    )
    perturb.write_text(
        f"illuminance_lux: {lux}\nperception_model_file: {_MODEL}\n", encoding="utf-8"
    )
    return [
        Parameter("topics_file", value=str(topics)),
        Parameter("perturb_file", value=str(perturb)),
        Parameter("seed", value=_SEED),
    ]


@pytest.mark.parametrize("lux", _LUX_LEVELS)
def test_point_cloud_relay(
    lux: float, ros_context: Context, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify deterministic output, retention, metadata, and QoS via DDS."""
    overrides = _write_parameters(tmp_path, lux)
    relay = PerceptionDegrader(context=ros_context, parameter_overrides=overrides)
    peer = Node("cloud_test", context=ros_context)
    executor = SingleThreadedExecutor(context=ros_context)
    executor.add_node(relay)
    executor.add_node(peer)
    received: list[PointCloud2] = []
    qos = QoSProfile(depth=_DEPTH, reliability=QoSReliabilityPolicy.BEST_EFFORT)
    sink = peer.create_subscription(PointCloud2, _OUTPUT, received.append, qos)
    source = peer.create_publisher(PointCloud2, _INPUT, qos)
    try:
        header = Header(frame_id="camera_optical_frame")
        header.stamp.sec = 123
        header.stamp.nanosec = 456
        xyz = np.tile(np.array([0.3, 0.0, 0.8], dtype=np.float32), (_SIZE, 1))
        # A NaN from the camera and a point beyond every configured range are both invalid.
        unmeasurable = np.array([[np.nan, 0.0, 0.0], [10.0, 0.0, 0.0]], dtype=np.float32)
        cloud = point_cloud2.create_cloud_xyz32(header, np.concatenate((xyz, unmeasurable)))

        deadline = monotonic() + 5.0
        while not received and monotonic() < deadline:
            source.publish(cloud)
            executor.spin_once(timeout_sec=0.1)
            executor.spin_once(timeout_sec=0.1)
        assert received, "Jazzy DDS did not deliver the relayed cloud"
        actual = received[0]
        assert actual.header == header
        # DDS discovery may not report endpoint history depth. Check the local profiles.
        depth_endpoints = [
            endpoint
            for endpoint in (*relay.publishers, *relay.subscriptions)
            if endpoint.topic_name in {_INPUT, _OUTPUT}
        ]
        assert {endpoint.topic_name for endpoint in depth_endpoints} == {_INPUT, _OUTPUT}
        assert all(endpoint.qos_profile.depth == _DEPTH for endpoint in depth_endpoints)
        assert all(
            endpoint.qos_profile.reliability == qos.reliability for endpoint in depth_endpoints
        )
        assert source.get_subscription_count() == 1
        assert sink.get_publisher_count() == 1

        model = PerceptionModel.from_yaml(_MODEL)
        lengths = np.linalg.norm(xyz.astype(np.float64), axis=1)
        expected = model.degrade(
            np.concatenate((lengths, [np.nan, 10.0])), lux, np.random.default_rng(_SEED)
        )[:_SIZE]
        retained = np.isfinite(expected)
        points = point_cloud2.read_points_numpy(actual, field_names=("x", "y", "z"))
        scaled = xyz[retained] * (expected[retained] / lengths[retained])[:, None]
        npt.assert_allclose(points, scaled)
        assert actual.width / _SIZE == pytest.approx(model.p_valid(model.eta(lux)), abs=0.012)
        events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        first = next(event for event in events if event["event"] == "perception.cloud_processed")
        assert first["input_points"] == _SIZE + len(unmeasurable)
        assert first["retained_points"] == actual.width
        assert 0.0 <= first["processing_ms"] < _CAMERA_PERIOD_MS
    finally:
        executor.shutdown()
        peer.destroy_node()
        relay.destroy_node()


def test_rejects_invalid_episode_setup(ros_context: Context, tmp_path: Path) -> None:
    """Reject invalid illuminance and refuse to relay onto the input topic."""
    with pytest.raises(ValueError, match="illuminance"):
        PerceptionDegrader(
            context=ros_context, parameter_overrides=_write_parameters(tmp_path, 0.0)
        )
    with pytest.raises(ValueError, match="distinct topics"):
        PerceptionDegrader(
            context=ros_context, parameter_overrides=_write_parameters(tmp_path, 50.0, _INPUT)
        )


def test_console_entry_starts_and_shuts_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use the pinned Jazzy startup API through the installed console entry."""
    overrides = _write_parameters(tmp_path, 50.0)
    args = ["--ros-args"]
    for override in overrides:
        args.extend(["-p", f"{override.name}:={override.value}"])

    spun: list[str] = []

    def spin(node: PerceptionDegrader) -> None:
        assert rclpy.ok()
        spun.append(node.get_name())
        raise KeyboardInterrupt

    monkeypatch.setattr(rclpy, "spin", spin)
    main(args)
    assert spun == ["perception_degrader"]
    assert not rclpy.ok()
