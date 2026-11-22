"""Optional ROS diagnostic publisher for in-process ground-truth measurements (T-094a)."""

from __future__ import annotations

from pathlib import Path
from typing import Final

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.executors import ExternalShutdownException
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import Float64MultiArray

from roboprobe_ros.base import RoboProbeNode
from roboprobe_ros.ground_truth_monitor import GroundTruthMonitor

_DIAGNOSTICS_TOPIC: Final = "/roboprobe/ground_truth"


class GroundTruthNode(RoboProbeNode):
    """Publish clearance, roll and pitch for live diagnosis."""

    def __init__(self) -> None:
        """Load a materialised episode and listen for its ground-truth poses."""
        super().__init__("ground_truth_monitor")
        try:
            self._configure()
        except Exception:
            self.destroy_node()
            raise

    def _configure(self) -> None:
        episode = self.declare_parameter("episode_file", "").get_parameter_value().string_value
        if not episode:
            msg = "ground_truth_monitor requires episode_file"
            raise ValueError(msg)
        self._monitor = GroundTruthMonitor.from_episode(Path(episode))
        self._publish = self.create_publisher(
            Float64MultiArray, _DIAGNOSTICS_TOPIC, qos_profile_sensor_data
        )
        self.create_subscription(
            PoseStamped,
            self.topic("ground_truth_pose"),
            self._observe,
            self.qos("ground_truth_pose"),
        )

    def _observe(self, msg: PoseStamped) -> None:
        position, rotation = msg.pose.position, msg.pose.orientation
        try:
            sample = self._monitor.evaluate(
                (position.x, position.y), (rotation.x, rotation.y, rotation.z, rotation.w)
            )
        except ValueError as error:
            self.get_logger().warning(f"Discarding invalid ground-truth pose: {error}")
            return
        self._publish.publish(
            Float64MultiArray(data=[sample.clearance_m, sample.roll_rad, sample.pitch_rad])
        )


def main(args: list[str] | None = None) -> None:
    """Run the diagnostics process until ROS shuts down."""
    rclpy.init(args=args)
    try:
        node = GroundTruthNode()
        try:
            rclpy.spin(node)
        finally:
            node.destroy_node()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        rclpy.try_shutdown()
