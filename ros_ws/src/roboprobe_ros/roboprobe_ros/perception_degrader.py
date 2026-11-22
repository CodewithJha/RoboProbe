"""ROS 2 camera relay for episode-constant low-light depth loss (FR-SIM-003)."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Final

import numpy as np
import rclpy
from rclpy.executors import ExternalShutdownException
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2

from roboprobe_ros._vendor.perturbation.perception import PerceptionModel
from roboprobe_ros.base import RoboProbeNode

if TYPE_CHECKING:
    from rclpy.context import Context
    from rclpy.parameter import Parameter

_FIELDS: Final = ("x", "y", "z")
_QUEUE_DEPTH: Final = 1


class PerceptionDegrader(RoboProbeNode):
    """Apply the configured radial depth model to the current camera frame."""

    def __init__(
        self,
        *,
        context: Context | None = None,
        parameter_overrides: list[Parameter] | None = None,
    ) -> None:
        """Load the versioned model and attach the two depth-one endpoints."""
        super().__init__(
            "perception_degrader", context=context, parameter_overrides=parameter_overrides
        )
        try:
            self._configure()
        except Exception:
            self.destroy_node()
            raise

    def _configure(self) -> None:
        illuminance = self.perturbation.get("illuminance_lux")
        if not isinstance(illuminance, int | float) or isinstance(illuminance, bool):
            msg = "perturb_params.yaml must specify numeric illuminance_lux"
            raise TypeError(msg)
        model_file = self.perturbation.get("perception_model_file")
        if not isinstance(model_file, str) or not model_file:
            msg = "perturb_params.yaml must specify perception_model_file"
            raise ValueError(msg)
        self._illuminance = float(illuminance)
        self._model = PerceptionModel.from_yaml(Path(model_file))
        self._model.eta(self._illuminance)

        raw = self.topic("depth_points_raw")
        processed = self.topic("depth_points")
        if self.resolve_topic_name(raw) == self.resolve_topic_name(processed):
            msg = "depth_points_raw and depth_points must resolve to distinct topics"
            raise ValueError(msg)
        raw_qos = self.qos("depth_points_raw")
        raw_qos.depth = _QUEUE_DEPTH
        processed_qos = self.qos("depth_points")
        processed_qos.depth = _QUEUE_DEPTH
        self._publisher = self.create_publisher(PointCloud2, processed, processed_qos)
        self.create_subscription(PointCloud2, raw, self._process_cloud, raw_qos)

    def _process_cloud(self, cloud: PointCloud2) -> None:
        started = perf_counter()
        xyz = point_cloud2.read_points_numpy(cloud, field_names=_FIELDS)
        coordinates = np.asarray(xyz, dtype=np.float64)
        ranges = np.linalg.norm(coordinates, axis=1)
        noisy = self._model.degrade(ranges, self._illuminance, self.rng)
        retained = np.isfinite(noisy)
        distances = ranges[retained]
        scale = np.divide(
            noisy[retained], distances, out=np.zeros_like(distances), where=distances > 0.0
        )
        points = (coordinates[retained] * scale[:, None]).astype(np.float32)
        self._publisher.publish(point_cloud2.create_cloud_xyz32(cloud.header, points))
        self.log_event(
            "perception.cloud_processed",
            input_points=len(coordinates),
            retained_points=len(points),
            processing_ms=(perf_counter() - started) * 1000,
        )


def main(args: list[str] | None = None) -> None:
    """Run the perception relay until ROS shuts down."""
    rclpy.init(args=args)
    try:
        node = PerceptionDegrader()
        try:
            rclpy.spin(node)
        finally:
            node.destroy_node()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        rclpy.try_shutdown()
