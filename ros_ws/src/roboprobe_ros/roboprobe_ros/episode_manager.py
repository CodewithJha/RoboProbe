"""Drive one Gazebo/Nav2 episode and report its result (T-094c, FR-SIM-003)."""

from __future__ import annotations

from math import cos, hypot, sin
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Final, Protocol

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from lifecycle_msgs.msg import State
from lifecycle_msgs.srv import GetState
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from std_msgs.msg import String
from std_srvs.srv import SetBool, Trigger

from roboprobe_ros.base import RoboProbeNode
from roboprobe_ros.episode_config import (
    EpisodeConfig,
    EpisodeResult,
    EpisodeTime,
    episode_exit_codes,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from rclpy.client import Client
    from rclpy.parameter import Parameter as ParameterValue

_POLL_S: Final = 0.05
_NS_PER_S: Final = 1_000_000_000
_STATUSES: Final = {
    GoalStatus.STATUS_SUCCEEDED: "SUCCEEDED",
    GoalStatus.STATUS_ABORTED: "ABORTED",
    GoalStatus.STATUS_CANCELED: "CANCELED",
}


class _RecorderResponse(Protocol):
    success: bool


class EpisodeManager(RoboProbeNode):
    """Wait for localization, navigate, flush the recorder and write episode_done.json."""

    def __init__(self, *, parameter_overrides: list[ParameterValue] | None = None) -> None:
        """Read the materialized episode and resolve its ROS endpoints."""
        super().__init__("episode_manager", parameter_overrides=parameter_overrides)
        try:
            self._configure()
        except Exception:
            self.destroy_node()
            raise

    def _configure(self) -> None:
        path = self.declare_parameter("episode_file", "").get_parameter_value().string_value
        self._destination = Path(path).with_name("episode_done.json")
        self._episode = EpisodeConfig.read(Path(path))
        self._pose = self.create_publisher(
            PoseWithCovarianceStamped, self.topic("initial_pose"), self.qos("initial_pose")
        )
        self._localized = False
        self._map_frame = self.frame("map")
        self.create_subscription(
            PoseWithCovarianceStamped,
            self.topic("amcl_pose"),
            self._localization,
            self.qos("amcl_pose"),
        )
        self._status = self.create_publisher(String, "/roboprobe/nav_status", 1)
        self._amcl_state = self.create_client(GetState, "amcl/get_state")
        self._nav_state = self.create_client(GetState, "bt_navigator/get_state")
        self._start_recording = self.create_client(Trigger, "episode_recorder/start")
        self._stop_recording = self.create_client(SetBool, "episode_recorder/stop")
        self._navigate = ActionClient(self, NavigateToPose, "navigate_to_pose")
        self._recoveries = 0
        self._codes = episode_exit_codes()

    def _sim_time(self) -> float:
        return int(self.get_clock().now().nanoseconds) / _NS_PER_S

    def _wait(self, ready: Callable[[], bool], remaining: Callable[[], float]) -> bool:
        while not ready():
            if (seconds := remaining()) <= 0.0:
                return False
            rclpy.spin_once(self, timeout_sec=min(seconds, _POLL_S))
        return True

    def _active(
        self, client: Client[GetState.Request, GetState.Response], remaining: Callable[[], float]
    ) -> bool:
        while self._wait(client.service_is_ready, remaining) and remaining() > 0.0:
            state = client.call_async(GetState.Request())
            if not self._wait(state.done, remaining):
                return False
            if state.result().current_state.id == State.PRIMARY_STATE_ACTIVE:
                return True
            rclpy.spin_once(self, timeout_sec=max(0.0, min(remaining(), _POLL_S)))
        return False

    def _stamp(self, coordinates: tuple[float, float, float]) -> PoseStamped:
        x, y, yaw = coordinates
        pose = PoseStamped()
        pose.header.frame_id = self._map_frame
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.pose.position.x, pose.pose.position.y = x, y
        pose.pose.orientation.z, pose.pose.orientation.w = sin(yaw / 2.0), cos(yaw / 2.0)
        return pose

    def _localization(self, message: PoseWithCovarianceStamped) -> None:
        position = message.pose.pose.position
        x, y, _ = self._episode.start
        self._localized = (
            message.header.frame_id == self._map_frame
            and hypot(position.x - x, position.y - y) <= self._episode.spawn_tolerance
        )

    def _spawn(self, remaining: Callable[[], float]) -> bool:
        if not self._wait(lambda: self._pose.get_subscription_count() > 0, remaining):
            return False
        stamped = self._stamp(self._episode.start)
        initial = PoseWithCovarianceStamped(header=stamped.header)
        initial.pose.pose = stamped.pose
        self._localized = False
        self._pose.publish(initial)
        return self._wait(lambda: self._localized, remaining)

    def _trigger[Request, Response: _RecorderResponse](
        self, client: Client[Request, Response], message: Request
    ) -> None:
        deadline = monotonic() + self._episode.startup_limit

        def remaining() -> float:
            return deadline - monotonic()

        if self._wait(client.service_is_ready, remaining):
            response = client.call_async(message)
            if self._wait(response.done, remaining) and response.result().success:
                return
        msg = f"Recorder service failed: {client.srv_name}"
        raise RuntimeError(msg)

    def _feedback(self, message: NavigateToPose.Impl.FeedbackMessage) -> None:
        self._recoveries = message.feedback.number_of_recoveries

    def _drive(self, start: EpisodeTime) -> tuple[str, int | None]:
        def remaining() -> float:
            return min(
                self._episode.wall_limit - (monotonic() - start.wall),
                self._episode.sim_limit - (self._sim_time() - start.sim),
            )

        goal = NavigateToPose.Goal(pose=self._stamp(self._episode.goal))
        pending = self._navigate.send_goal_async(goal, feedback_callback=self._feedback)
        if not self._wait(pending.done, remaining):
            return "TIMEOUT", None
        handle = pending.result()
        if not handle.accepted:
            return "ABORTED", GoalStatus.STATUS_ABORTED
        result = handle.get_result_async()
        if not self._wait(result.done, remaining):
            handle.cancel_goal_async()
            return "TIMEOUT", None
        code = result.result().status
        return _STATUSES[code], code

    def run(self) -> int:
        """Run the episode and return the exit code shared with the backend."""
        start = EpisodeTime.capture(self._sim_time())
        code = None
        finished = None

        def remaining() -> float:
            return self._episode.startup_limit - (monotonic() - start.wall)

        if not self._active(self._amcl_state, remaining):
            status = "STARTUP_TIMEOUT"
        elif not self._spawn(remaining):
            status = "SPAWN_FAILED"
        elif not self._active(self._nav_state, remaining) or not self._wait(
            self._navigate.server_is_ready, remaining
        ):
            status = "STARTUP_TIMEOUT"
        else:
            self._trigger(self._start_recording, Trigger.Request())
            start = EpisodeTime.capture(self._sim_time())
            self._status.publish(String(data="ACTIVE"))
            complete = False
            try:
                status, code = self._drive(start)
                complete = status != "TIMEOUT"
                self._status.publish(String(data=status))
            finally:
                finished = EpisodeTime.capture(self._sim_time())
                self._trigger(self._stop_recording, SetBool.Request(data=complete))
        end = finished or EpisodeTime.capture(self._sim_time())
        EpisodeResult(status, code, start, end, self._recoveries).write(self._destination)
        return self._codes.get(status.lower(), self._codes["completed"])


def main(args: list[str] | None = None) -> int:
    """Run and release the episode manager, classifying unexpected failures."""
    rclpy.init(args=args)
    try:
        manager = EpisodeManager()
        try:
            return manager.run()
        finally:
            manager.destroy_node()
    except (KeyboardInterrupt, Exception) as exc:
        rclpy.logging.get_logger("episode_manager").error(str(exc))
        return episode_exit_codes()["internal_error"]
    finally:
        rclpy.try_shutdown()
