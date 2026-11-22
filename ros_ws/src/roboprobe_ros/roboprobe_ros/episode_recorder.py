"""Record Gazebo simulation telemetry in Trace v1 and optional MCAP (T-094b).

Implements: FR-RUN-004, FR-SIM-003, FR-SIM-005
"""

from __future__ import annotations

import math
import signal
import subprocess
from dataclasses import replace
from pathlib import Path
from shutil import which
from tempfile import TemporaryDirectory
from time import monotonic_ns
from typing import TYPE_CHECKING, Any, Literal, Protocol

import numpy as np
import rclpy
import yaml
from geometry_msgs.msg import (
    PoseStamped,
    PoseWithCovarianceStamped,
    Quaternion,
    Twist,
    TwistStamped,
)
from nav2_msgs.msg import BehaviorTreeLog
from nav_msgs.msg import Odometry
from pydantic import BaseModel, Field
from rclpy.executors import ExternalShutdownException
from rclpy.parameter import Parameter
from std_msgs.msg import Float64, String
from std_srvs.srv import SetBool, Trigger

from roboprobe_ros._vendor.trace import Trace
from roboprobe_ros._vendor.trace_enums import NavStatus
from roboprobe_ros._vendor.trace_io import TRACE_SCHEMA, read_trace, validate_trace, write_trace
from roboprobe_ros.base import RoboProbeNode

if TYPE_CHECKING:
    from rclpy.context import Context
    from rclpy.timer import Timer

_NS_PER_SECOND = 1_000_000_000
_CONTROL_QUEUE_DEPTH = 10
_TRACE_MIN_HZ = 10.0  # FR-RUN-004
_TRACE_MAX_GAP_S = 0.2  # FR-RUN-004
_NAV_STATUS_TOPIC = "/roboprobe/nav_status"
_COMMAND_DELAY_TOPIC = "/roboprobe/cmd_delay_actual"
_RECOVERY_NODES = frozenset(
    {
        "BackUp",
        "ClearGlobalCostmap-Context",
        "ClearGlobalCostmap-Subtree",
        "ClearLocalCostmap-Context",
        "ClearLocalCostmap-Subtree",
        "Spin",
        "Wait",
    }
)


class _Goal(BaseModel):
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


class _Config(BaseModel):
    goal: _Goal
    sample_hz: float = Field(gt=0, allow_inf_nan=False)
    record_bag: Literal["never", "failures", "always"]
    teardown_grace_s: float = Field(gt=0, allow_inf_nan=False)


class GroundTruthSample(Protocol):
    """Fields required from a ground-truth monitor observation."""

    @property
    def clearance_m(self) -> float:
        """Return the distance to the nearest obstacle in metres."""
        ...

    @property
    def roll_rad(self) -> float:
        """Return roll in radians."""
        ...

    @property
    def pitch_rad(self) -> float:
        """Return pitch in radians."""
        ...

    @property
    def yaw_rad(self) -> float:
        """Return yaw in radians."""
        ...


class ClearanceProvider(Protocol):
    """Calculate geometry and attitude for one Gazebo ground-truth pose."""

    def evaluate(
        self, position: tuple[float, float], quaternion: tuple[float, float, float, float]
    ) -> GroundTruthSample:
        """Measure the footprint clearance and attitude at the given pose."""
        ...


def _yaw(q: Quaternion) -> float:
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


class EpisodeRecorder(RoboProbeNode):
    """Sample cached ROS messages on the episode's simulation clock."""

    def __init__(
        self,
        *,
        monitor: ClearanceProvider | None = None,
        context: Context | None = None,
        parameter_overrides: list[Parameter] | None = None,
    ) -> None:
        """Load the episode file and connect to the configured telemetry topics."""
        overrides = [*(parameter_overrides or ()), Parameter("use_sim_time", value=True)]
        super().__init__("episode_recorder", context=context, parameter_overrides=overrides)
        try:
            episode = self.declare_parameter("episode_file", Parameter.Type.STRING)
            self._episode_file = Path(episode.get_parameter_value().string_value).resolve(
                strict=True
            )
            self._config = _Config.model_validate(
                yaml.safe_load(self._episode_file.read_text(encoding="utf-8"))
            )
            if monitor is None:
                from roboprobe_ros.ground_truth_monitor import GroundTruthMonitor  # noqa: PLC0415

                monitor = GroundTruthMonitor.from_episode(self._episode_file)
            self._monitor = monitor
            self._columns: dict[str, list[float | bool | int]] = {
                name: [] for name in TRACE_SCHEMA.names
            }
            self._start_ns: int | None = None
            self._last_wall_ns = 0
            self._timer: Timer | None = None
            self._flushed = False
            self._bag: subprocess.Popen[bytes] | None = None
            self._gt: PoseStamped | None = None
            self._estimate: PoseWithCovarianceStamped | None = None
            self._odom: Odometry | None = None
            self._command = Twist()
            self._nav_status = NavStatus.IDLE
            self._recoveries = 0
            self._max_delay_s = 0.0
            self._subscribe()
            self.create_service(Trigger, "/episode_recorder/start", self._start)
            self.create_service(SetBool, "/episode_recorder/stop", self._stop)
        except Exception:
            self.destroy_node()
            raise

    def _subscribe(self) -> None:
        self.create_subscription(
            PoseStamped,
            self.topic("ground_truth_pose"),
            lambda message: setattr(self, "_gt", message),
            self.qos("ground_truth_pose"),
        )
        self.create_subscription(
            PoseWithCovarianceStamped,
            self.topic("amcl_pose"),
            lambda message: setattr(self, "_estimate", message),
            self.qos("amcl_pose"),
        )
        self.create_subscription(
            Odometry,
            self.topic("odom"),
            lambda message: setattr(self, "_odom", message),
            self.qos("odom"),
        )
        command_type = TwistStamped if self.stamped_cmd_vel else Twist
        self.create_subscription(
            command_type, self.topic("cmd_vel"), self._cache_command, self.qos("cmd_vel")
        )
        self.create_subscription(
            String, _NAV_STATUS_TOPIC, self._cache_status, _CONTROL_QUEUE_DEPTH
        )
        self.create_subscription(
            Float64, _COMMAND_DELAY_TOPIC, self._cache_delay, _CONTROL_QUEUE_DEPTH
        )
        self.create_subscription(
            BehaviorTreeLog, self.topic("bt_log"), self._cache_bt, self.qos("bt_log")
        )

    def _cache_command(self, message: Twist | TwistStamped) -> None:
        self._command = message.twist if isinstance(message, TwistStamped) else message

    def _cache_status(self, message: String) -> None:
        status = "CANCELED" if message.data == "TIMEOUT" else message.data
        self._nav_status = NavStatus.__members__.get(status, self._nav_status)

    def _cache_delay(self, message: Float64) -> None:
        if self._start_ns is not None and math.isfinite(message.data):
            self._max_delay_s = max(self._max_delay_s, message.data)

    def _cache_bt(self, message: BehaviorTreeLog) -> None:
        if self._start_ns is not None:
            self._recoveries += sum(
                event.node_name in _RECOVERY_NODES
                and event.previous_status == "IDLE"
                and event.current_status in {"RUNNING", "SUCCESS", "FAILURE"}
                for event in message.event_log
            )

    @property
    def ready_to_sample(self) -> bool:
        """Whether ground truth, AMCL, and odometry have all arrived."""
        return self._gt is not None and self._estimate is not None and self._odom is not None

    @property
    def sample_count(self) -> int:
        """Number of recorded simulation samples."""
        return len(self._columns["t"])

    def _start(self, _request: Trigger.Request, response: Trigger.Response) -> Trigger.Response:
        if self._start_ns is not None:
            response.success = not self._flushed
            response.message = "episode already started"
            return response
        try:
            if self._config.record_bag == "always":
                self._start_bag()
            self._timer = self.create_timer(1.0 / self._config.sample_hz, self._sample)
            self._start_ns = self.get_clock().now().nanoseconds
            self._last_wall_ns = monotonic_ns()
        except (OSError, RuntimeError) as exc:
            self._stop_bag()
            response.message = str(exc)
            return response
        response.success = True
        return response

    def _sample(self) -> None:
        if (
            self._start_ns is None
            or self._gt is None
            or self._estimate is None
            or self._odom is None
        ):
            return
        t = (self.get_clock().now().nanoseconds - self._start_ns) / _NS_PER_SECOND
        times = self._columns["t"]
        if t <= (times[-1] if times else 0.0):
            return
        position, orientation = self._gt.pose.position, self._gt.pose.orientation
        truth = self._monitor.evaluate(
            (position.x, position.y), (orientation.x, orientation.y, orientation.z, orientation.w)
        )
        estimate = self._estimate.pose.pose
        measured = self._odom.twist.twist
        wall_ns = monotonic_ns()
        wall_elapsed = (wall_ns - self._last_wall_ns) / _NS_PER_SECOND
        rtf = (t - (times[-1] if times else 0.0)) / wall_elapsed if wall_elapsed > 0 else 0.0
        self._last_wall_ns = wall_ns
        row = {
            "t": t,
            "gt_x": position.x,
            "gt_y": position.y,
            "gt_yaw": truth.yaw_rad,
            "est_x": estimate.position.x,
            "est_y": estimate.position.y,
            "est_yaw": _yaw(estimate.orientation),
            "cmd_v": self._command.linear.x,
            "cmd_w": self._command.angular.z,
            "meas_v": measured.linear.x,
            "meas_w": measured.angular.z,
            "min_obstacle_dist": truth.clearance_m,
            "contact": truth.clearance_m <= 0.0,
            "roll": truth.roll_rad,
            "pitch": truth.pitch_rad,
            "nav_status": self._nav_status,
            "rtf": rtf,
        }
        for name, value in row.items():
            self._columns[name].append(value)

    def _stop(self, request: SetBool.Request, response: SetBool.Response) -> SetBool.Response:
        if self._start_ns is None:
            response.message = "episode has not started"
            return response
        try:
            self.flush(complete=request.data)
        except (OSError, RuntimeError, ValueError) as exc:
            response.message = str(exc)
            return response
        response.success = True
        return response

    def flush(self, *, complete: bool) -> None:
        """Validate and atomically publish a single Trace v1 file, then stop the bag."""
        if self._start_ns is None or self._flushed:
            return
        if self._timer is not None:
            self._timer.cancel()
        try:
            self._write_trace(complete)
            self._flushed = True
        finally:
            self._stop_bag()

    def _write_trace(self, complete: bool) -> None:
        special_dtypes = {"contact": np.bool_, "nav_status": np.int8, "rtf": np.float32}
        columns: dict[str, Any] = {
            name: np.asarray(values, dtype=special_dtypes.get(name, np.float64))
            for name, values in self._columns.items()
        }
        trace = Trace(
            **columns,
            goal_x=self._config.goal.x,
            goal_y=self._config.goal.y,
            meta={
                "backend": "gazebo_nav2",
                "complete": complete,
                "sample_hz": self._config.sample_hz,
                "n_recoveries": self._recoveries,
                "cmd_delay_max_s": self._max_delay_s,
            },
        )
        problems = validate_trace(trace, min_hz=_TRACE_MIN_HZ, max_gap_s=_TRACE_MAX_GAP_S)
        if problems:
            trace = replace(
                trace, meta={**trace.meta, "complete": False, "warnings": list(problems)}
            )
        final = self._episode_file.with_name("trace.parquet")
        with TemporaryDirectory(prefix=".trace-", dir=final.parent) as directory:
            staged = Path(directory) / final.name
            write_trace(trace, staged)
            read_trace(staged)
            staged.replace(final)

    def _start_bag(self) -> None:
        ros2 = which("ros2")
        if not ros2:
            msg = "ros2 must be available to record an MCAP"
            raise FileNotFoundError(msg)
        topics = [self.topic(key) for key in ("scan", "cmd_vel", "amcl_pose", "ground_truth_pose")]
        resolved = dict.fromkeys(map(self.resolve_topic_name, [*topics, "/tf"]))
        self._bag = subprocess.Popen(  # noqa: S603 - ROS names and path are separate argv entries
            [
                ros2,
                "bag",
                "record",
                "-s",
                "mcap",
                "--use-sim-time",
                "-o",
                str(self._episode_file.with_name("bag")),
                "--topics",
                *resolved,
            ],
            stdin=subprocess.DEVNULL,
        )

    def _stop_bag(self) -> None:
        if (bag := self._bag) is None:
            return
        self._bag = None
        grace = self._config.teardown_grace_s
        for stop_signal in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
            if bag.poll() is None:
                bag.send_signal(stop_signal)
            try:
                status = bag.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                continue
            if status not in {0, -signal.SIGINT}:
                msg = f"rosbag2 recorder exited with status {status}"
                raise RuntimeError(msg)
            return
        msg = "rosbag2 recorder failed to exit"
        raise RuntimeError(msg)


def main(args: list[str] | None = None) -> None:
    """Spin the installed recorder and flush partial telemetry on shutdown."""
    rclpy.init(args=args)
    node = None
    try:
        node = EpisodeRecorder()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        try:
            if node is not None:
                try:
                    node.flush(complete=False)
                finally:
                    node.destroy_node()
        finally:
            rclpy.try_shutdown()
