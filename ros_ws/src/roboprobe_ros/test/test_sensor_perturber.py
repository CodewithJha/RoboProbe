"""Exercise the installed lidar node over real Jazzy ROS messages (T-093b)."""

# ruff: noqa: S101

from __future__ import annotations

import json
from array import array
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from copy import copy
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from unittest import TestCase

import launch
import launch_testing
import numpy as np
import numpy.testing as npt
import pytest
import rclpy
import yaml
from launch_ros.actions import Node
from launch_testing.actions import ReadyToTest
from numpy.random import PCG64, Generator
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.parameter import Parameter
from rclpy.qos import qos_profile_sensor_data, qos_profile_system_default
from rclpy.serialization import serialize_message
from roboprobe_ros._vendor.perturbation.lidar import apply_dropout, apply_lidar_noise
from roboprobe_ros.sensor_perturber import SensorPerturber
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String

_N_SCANS = 10
_BEAMS_PER_SCAN = 1_000
_N_BEAMS = _N_SCANS * _BEAMS_PER_SCAN
_SIGMA_M = 0.10
_DROPOUT = 0.20
_SEED = 20261119
_RANGE_M = 10.0
_MIN_M = 0.25
_MAX_M = 30.0
_RAW = "/lidar_test/scan_raw"
_NODES = ("first", "second")
_STATS = "/roboprobe/perturber_stats"


def _write_config(path: Path, data: dict[str, object]) -> str:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(path)


def _test_topic(name: str, kind: str) -> str:
    return f"/lidar_test/{name}/{kind}"


def _topics_data(scan: str) -> dict[str, object]:
    mappings = (("scan_raw", _RAW), ("scan", scan))
    return {"topics": {key: {"name": name, "qos": "sensor_data"} for key, name in mappings}}


@pytest.mark.launch_test
def generate_test_description() -> tuple[launch.LaunchDescription, dict[str, object]]:
    """Launch two installed processes with an identical episode seed."""
    files = TemporaryDirectory(prefix="roboprobe-lidar-")
    root = Path(files.name)
    perturb_file = _write_config(
        root / "perturb_params.yaml",
        {"seed": _SEED, "lidar": {"sigma_m": _SIGMA_M, "dropout_p": _DROPOUT}},
    )
    nodes = []
    for name in _NODES:
        topics_file = _write_config(root / f"{name}.yaml", _topics_data(_test_topic(name, "scan")))
        nodes.append(
            Node(
                package="roboprobe_ros",
                executable="sensor_perturber",
                name=f"test_lidar_{name}",
                parameters=[{"topics_file": topics_file, "perturb_file": perturb_file}],
                remappings=[(_STATS, _test_topic(name, "stats"))],
            )
        )
    return launch.LaunchDescription([*nodes, ReadyToTest()]), {"test_files": files}


def _wait(executor: SingleThreadedExecutor, predicate: Callable[[], bool], timeout: float) -> None:
    deadline = monotonic() + timeout
    while not predicate():
        remaining = deadline - monotonic()
        if remaining <= 0.0:
            pytest.fail("Timed out waiting for lidar ROS messages")
        executor.spin_once(timeout_sec=min(0.1, remaining))


def _scan(ranges: array[float], *, index: int) -> LaserScan:
    scan = LaserScan()
    scan.header.frame_id = "rplidar_test_link"
    scan.header.stamp.sec = index + 7
    scan.header.stamp.nanosec = 123_456
    scan.angle_min = -0.5
    scan.angle_max = 0.5
    scan.angle_increment = 0.001
    scan.time_increment = 0.0001
    scan.scan_time = 0.1
    scan.range_min = _MIN_M
    scan.range_max = _MAX_M
    scan.ranges = ranges
    scan.intensities = array("f", [2.5]) * len(ranges)
    return scan


def _assert_metadata_equal(actual: LaserScan, expected: LaserScan) -> None:
    restored = copy(actual)
    restored.ranges = expected.ranges
    assert serialize_message(restored) == serialize_message(expected)


@contextmanager
def _ros_context() -> Iterator[Context]:
    """Run each harness node in its own rclpy context."""
    context = Context()
    rclpy.init(context=context)
    try:
        yield context
    finally:
        rclpy.try_shutdown(context=context)


class TestSensorPerturber(TestCase):
    """Check the installed processes with live DDS subscribers and publishers."""

    def test_ros_scans_have_repeatable_noise_dropout_and_metadata(self) -> None:
        """Check seeded replay and statistics across 10,000 original ranges."""
        with _ros_context() as context:
            self._verify_ros_scans(context)

    def _verify_ros_scans(self, context: Context) -> None:
        node = rclpy.create_node("lidar_test_client", context=context)
        executor = SingleThreadedExecutor(context=context)
        executor.add_node(node)
        output: list[list[LaserScan]] = [[], []]
        stats: list[list[String]] = [[], []]
        try:
            scan_input = node.create_publisher(LaserScan, _RAW, qos_profile_sensor_data)
            subscribers = [
                node.create_subscription(
                    LaserScan,
                    _test_topic(name, "scan"),
                    output[index].append,
                    qos_profile_sensor_data,
                )
                for index, name in enumerate(_NODES)
            ]
            for index, name in enumerate(_NODES):
                node.create_subscription(
                    String,
                    _test_topic(name, "stats"),
                    stats[index].append,
                    qos_profile_system_default,
                )
            _wait(
                executor,
                lambda: (
                    scan_input.get_subscription_count() == len(_NODES)
                    and all(sub.get_publisher_count() == 1 for sub in subscribers)
                ),
                timeout=15.0,
            )
            for name in _NODES:
                [endpoint] = node.get_publishers_info_by_topic(_test_topic(name, "scan"))
                assert endpoint.qos_profile.reliability == qos_profile_sensor_data.reliability
            ranges = array("f", [_RANGE_M]) * _BEAMS_PER_SCAN
            for index in range(_N_SCANS):
                scan = _scan(ranges, index=index)
                scan_input.publish(scan)
                _wait(
                    executor,
                    lambda index=index: all(len(scans) > index for scans in output),
                    timeout=3.0,
                )
                for scans in output:
                    _assert_metadata_equal(scans[index], scan)
                npt.assert_array_equal(output[0][index].ranges, output[1][index].ranges)
            rng = Generator(PCG64(_SEED))
            noisy = apply_lidar_noise(ranges, _SIGMA_M, rng, _MIN_M, _MAX_M)
            expected_scan = apply_dropout(noisy, _DROPOUT, rng).astype(np.float32)
            npt.assert_array_equal(output[0][0].ranges, expected_scan)

            measured = np.concatenate([np.asarray(scan.ranges) for scan in output[0]])
            dropped = int(np.count_nonzero(np.isposinf(measured)))
            finite = measured[np.isfinite(measured)]
            assert measured.size == _N_BEAMS
            assert np.std(finite - _RANGE_M) == pytest.approx(_SIGMA_M, rel=0.10)
            assert dropped / _N_BEAMS == pytest.approx(_DROPOUT, abs=0.02)
            expected = {"count": _N_BEAMS, "dropped": dropped}
            _wait(
                executor,
                lambda: all(
                    any(json.loads(msg.data) == expected for msg in group) for group in stats
                ),
                timeout=5.0,
            )

            edge_ranges = array("f", [float("inf"), float("-inf"), float("nan"), -400.0, 400.0])
            edge_scan = _scan(edge_ranges * 20, index=_N_SCANS)
            scan_input.publish(edge_scan)
            _wait(executor, lambda: all(len(scans) > _N_SCANS for scans in output), timeout=3.0)
            edges = np.asarray(output[0][-1].ranges).reshape(-1, len(edge_ranges))
            assert np.isposinf(edges[:, 0]).all()
            assert np.isneginf(edges[:, 1]).all()
            assert np.isnan(edges[:, 2]).all()
            assert np.count_nonzero(edges[:, 3] == _MIN_M) > 0
            assert np.count_nonzero(edges[:, 4] == _MAX_M) > 0
            assert np.isin(edges[:, 3], [_MIN_M, np.inf]).all()
            assert np.isin(edges[:, 4], [_MAX_M, np.inf]).all()
            npt.assert_array_equal(output[0][-1].ranges, output[1][-1].ranges)
        finally:
            executor.shutdown()
            node.destroy_node()

    def test_rejects_same_resolved_input_and_output(self) -> None:
        """Refuse to subscribe to the node's own outgoing scan topic."""
        with TemporaryDirectory(prefix="roboprobe-lidar-invalid-") as directory:
            root = Path(directory)
            topics = _write_config(root / "topics.yaml", _topics_data(_RAW))
            params = _write_config(
                root / "perturb_params.yaml",
                {"seed": 1, "lidar": {"sigma_m": 0, "dropout_p": 0}},
            )
            with _ros_context() as context, pytest.raises(ValueError, match="different ROS topics"):
                SensorPerturber(
                    context=context,
                    parameter_overrides=[
                        Parameter("topics_file", value=topics),
                        Parameter("perturb_file", value=params),
                    ],
                )


@launch_testing.post_shutdown_test()
class TestLidarShutdown(TestCase):
    """Verify the installed processes shut down cleanly."""

    def test_release_nodes(self, proc_info: object, test_files: TemporaryDirectory[str]) -> None:
        """Verify normal exit status and release the fixture files."""
        self.addCleanup(test_files.cleanup)
        launch_testing.asserts.assertExitCodes(proc_info)
