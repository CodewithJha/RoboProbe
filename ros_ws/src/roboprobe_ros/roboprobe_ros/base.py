"""Shared ROS parameter, topic, and logging interfaces (T-093a, FR-SIM-003)."""

from __future__ import annotations

import json
from copy import copy
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

import yaml
from ament_index_python.packages import get_package_share_directory
from numpy.random import PCG64, Generator
from rclpy.node import Node
from rclpy.qos import QoSProfile, qos_profile_sensor_data

if TYPE_CHECKING:
    from rclpy.context import Context
    from rclpy.parameter import Parameter

__all__ = ["RoboProbeNode"]

_ROS_DEFAULT_QUEUE_DEPTH: Final = 10
_PACKAGE: Final = "roboprobe_ros"


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        msg = f"{label} must be a mapping with string keys"
        raise ValueError(msg)
    return {str(key): item for key, item in value.items()}


def _read_yaml(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as stream:
        return _mapping(yaml.safe_load(stream), str(path))


def _stamped_cmd_vel(config: dict[str, object]) -> bool:
    stamped = config.get("stamped_cmd_vel", False)
    if not isinstance(stamped, bool):
        msg = "stamped_cmd_vel must be a boolean"
        raise TypeError(msg)
    return stamped


class RoboProbeNode(Node):
    """Load generated episode data and expose deterministic node utilities."""

    def __init__(
        self,
        name: str,
        *,
        context: Context | None = None,
        parameter_overrides: list[Parameter] | None = None,
    ) -> None:
        """Declare the configuration paths and seed before creating subscribers."""
        super().__init__(name, context=context, parameter_overrides=parameter_overrides)
        try:
            packaged_topics = Path(get_package_share_directory(_PACKAGE)) / "config" / "topics.yaml"
            topic_file = self.declare_parameter("topics_file", str(packaged_topics))
            perturb_file = self.declare_parameter("perturb_file", "")
            seed = self.declare_parameter("seed", 0)
            topics_path = Path(topic_file.get_parameter_value().string_value)
            perturb_path = perturb_file.get_parameter_value().string_value
            self._catalog = _read_yaml(topics_path)
            self._topics = _mapping(self._catalog.get("topics"), "topics")
            self.stamped_cmd_vel = _stamped_cmd_vel(self._catalog)
            self.perturbation = _read_yaml(Path(perturb_path)) if perturb_path else {}
            self.rng = Generator(PCG64(seed.get_parameter_value().integer_value))
        except Exception:
            # ROS resources are already allocated at this point.
            self.destroy_node()
            raise

    def topic(self, key: str) -> str:
        """Resolve a logical topic key to its configured ROS name."""
        record = _mapping(self._topics[key], f"topics.{key}")
        name = record.get("name")
        if not isinstance(name, str) or not name:
            msg = f"topics.{key}.name must be a nonempty string"
            raise ValueError(msg)
        return name

    def qos(self, key: str) -> QoSProfile:
        """Resolve the delivery profile used by the named topic."""
        record = _mapping(self._topics[key], f"topics.{key}")
        profile = record.get("qos")
        if profile == "sensor_data":
            return copy(qos_profile_sensor_data)
        if profile == "default":
            return QoSProfile(depth=_ROS_DEFAULT_QUEUE_DEPTH)
        msg = f"topics.{key}.qos must name a supported QoS profile"
        raise ValueError(msg)

    def frame(self, key: str) -> str:
        """Resolve a logical frame to its configured tf frame identifier."""
        value = _mapping(self._catalog.get("frames"), "frames")[key]
        if not isinstance(value, str) or not value:
            msg = f"frames.{key} must be a nonempty string"
            raise ValueError(msg)
        return value

    def log_event(self, event: str, **fields: object) -> None:
        """Write one JSON event with the common backend log fields."""
        entry = {
            **fields,
            "event": event,
            "logger": self.get_name(),
            "service": _PACKAGE,
            "level": "info",
            "ts": datetime.now(UTC).isoformat(),
        }
        print(json.dumps(entry, allow_nan=False), flush=True)
