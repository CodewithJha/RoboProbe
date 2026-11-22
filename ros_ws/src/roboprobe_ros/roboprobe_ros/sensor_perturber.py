"""Apply reproducible P4 range noise and P8 dropout to Jazzy scans (T-093b, FR-SIM-003)."""

from __future__ import annotations

import json
from array import array
from copy import copy
from math import isfinite
from typing import TYPE_CHECKING, Final

import numpy as np
import rclpy
from numpy.random import PCG64, Generator
from rclpy.executors import ExternalShutdownException
from rclpy.qos import qos_profile_system_default
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String

from roboprobe_ros._vendor.perturbation.lidar import apply_dropout, apply_lidar_noise
from roboprobe_ros.base import RoboProbeNode

if TYPE_CHECKING:
    from rclpy.context import Context
    from rclpy.parameter import Parameter

__all__ = ["SensorPerturber", "main"]

_STATS_TOPIC: Final = "/roboprobe/perturber_stats"
_STATS_PERIOD_S: Final = 1.0


def _number(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        msg = f"lidar.{key} must be a finite number"
        raise ValueError(msg)
    return float(value)


class SensorPerturber(RoboProbeNode):
    """Relay LaserScan messages using a single deterministic episode RNG."""

    def __init__(
        self,
        *,
        context: Context | None = None,
        parameter_overrides: list[Parameter] | None = None,
    ) -> None:
        """Read the episode YAML once and establish the raw and processed topics."""
        super().__init__(
            "sensor_perturber", context=context, parameter_overrides=parameter_overrides
        )
        try:
            self._configure()
        except Exception:
            self.destroy_node()
            raise

    def _configure(self) -> None:
        lidar = self.perturbation.get("lidar")
        if not isinstance(lidar, dict):
            msg = "perturb_params.yaml must contain a lidar mapping"
            raise TypeError(msg)
        self._sigma = _number(lidar.get("sigma_m"), "sigma_m")
        self._dropout = _number(lidar.get("dropout_p"), "dropout_p")
        if self._sigma < 0.0 or not 0.0 <= self._dropout <= 1.0:
            msg = "lidar.sigma_m must be nonnegative and lidar.dropout_p must be in [0, 1]"
            raise ValueError(msg)
        seed = self.perturbation.get("seed")
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            msg = "perturb_params.yaml seed must be a nonnegative integer"
            raise ValueError(msg)
        self.rng = Generator(PCG64(seed))
        self._count = 0
        self._dropped = 0
        raw = self.topic("scan_raw")
        output = self.topic("scan")
        if self.resolve_topic_name(raw) == self.resolve_topic_name(output):
            msg = "scan_raw and scan must resolve to different ROS topics"
            raise ValueError(msg)
        self._scan = self.create_publisher(LaserScan, output, self.qos("scan"))
        self._stats = self.create_publisher(String, _STATS_TOPIC, qos_profile_system_default)
        self.create_subscription(LaserScan, raw, self._perturb, self.qos("scan_raw"))
        self.create_timer(_STATS_PERIOD_S, self._publish_stats)

    def _perturb(self, scan: LaserScan) -> None:
        original = np.asarray(scan.ranges)
        try:
            noisy = apply_lidar_noise(
                original, self._sigma, self.rng, scan.range_min, scan.range_max
            )
        except ValueError as exc:
            self.get_logger().warning(f"Ignoring a lidar scan with invalid range bounds: {exc}")
            return
        ranges = apply_dropout(noisy, self._dropout, self.rng)
        finite = np.isfinite(original)
        # Preserve REP-117 values while still consuming a draw for every beam.
        ranges[~finite] = original[~finite]
        self._count += original.size
        self._dropped += int(np.count_nonzero(finite & np.isposinf(ranges)))

        output = copy(scan)
        output.ranges = array("f", ranges)
        self._scan.publish(output)

    def _publish_stats(self) -> None:
        data = json.dumps({"count": self._count, "dropped": self._dropped})
        self._stats.publish(String(data=data))


def main(args: list[str] | None = None) -> None:
    """Start the lidar relay and release its ROS resources on shutdown."""
    rclpy.init(args=args)
    try:
        node = SensorPerturber()
        try:
            rclpy.spin(node)
        finally:
            node.destroy_node()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        rclpy.try_shutdown()
