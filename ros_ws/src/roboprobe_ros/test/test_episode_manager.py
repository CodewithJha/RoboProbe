# ruff: noqa: PLR2004, S101
"""Drive the installed manager against mock Jazzy Nav2 and recorder endpoints."""

from __future__ import annotations

import json
from threading import Thread
from typing import TYPE_CHECKING

import pytest
import rclpy
import yaml
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseWithCovarianceStamped
from lifecycle_msgs.msg import State
from lifecycle_msgs.srv import GetState
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionServer, CancelResponse
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile
from rclpy.task import Future
from roboprobe_ros.episode_manager import EpisodeManager, main
from rosgraph_msgs.msg import Clock
from std_srvs.srv import SetBool, Trigger

if TYPE_CHECKING:
    from pathlib import Path

    from rclpy.action.server import ServerGoalHandle


@pytest.mark.parametrize(
    ("case", "status", "nav_code", "exit_code"),
    [
        ("success", "SUCCEEDED", GoalStatus.STATUS_SUCCEEDED, 0),
        ("abort", "ABORTED", GoalStatus.STATUS_ABORTED, 0),
        ("sim_timeout", "TIMEOUT", None, 0),
        ("wall_timeout", "TIMEOUT", None, 0),
        ("startup_timeout", "STARTUP_TIMEOUT", None, 10),
        ("spawn_failed", "SPAWN_FAILED", None, 11),
    ],
)
def test_episode(
    tmp_path: Path, case: str, status: str, nav_code: int | None, exit_code: int
) -> None:
    """Check terminal status, recorder flushing, and simulated and wall deadlines."""
    episode = tmp_path / "episode.yaml"
    pose = {"x": 1.0, "y": 2.0, "yaw": 0.25}
    config = {
        "start": pose,
        "goal": {**pose, "x": 3.0},
        "time_limit_s": 2.0,
        "startup_timeout_s": 0.6 if case == "startup_timeout" else 3.0,
        "wall_timeout_factor": 0.25 if case == "wall_timeout" else 5.0,
        "spawn_tolerance_m": 0.2,
    }
    episode.write_text(yaml.safe_dump(config), encoding="utf-8")
    events: list[str | tuple[str, bool]] = []
    rclpy.init()
    mock = Node("mock_nav2")
    executor = SingleThreadedExecutor()
    executor.add_node(mock)
    server = _serve(mock, case, events)
    thread = Thread(target=executor.spin)
    thread.start()
    try:
        manager = EpisodeManager(
            parameter_overrides=[
                Parameter("episode_file", value=str(episode)),
                Parameter("use_sim_time", value=True),
            ]
        )
        try:
            assert manager.run() == exit_code
        finally:
            manager.destroy_node()
        result = json.loads((tmp_path / "episode_done.json").read_text(encoding="utf-8"))
        assert result["status"] == status
        assert result["nav_result_code"] == nav_code
        assert result["t_start"] <= result["t_end"]
        if exit_code == 0:
            assert events == ["pose", "start", "goal", ("stop", status != "TIMEOUT")]
        if case == "sim_timeout":
            assert result["sim_time_s"] == pytest.approx(2.0, abs=0.25)
            assert result["wall_time_s"] < 2.0
        if case == "wall_timeout":
            assert result["sim_time_s"] == 0.0
            assert result["wall_time_s"] == pytest.approx(0.5, abs=0.2)
    finally:
        executor.shutdown(timeout_sec=5.0)
        thread.join(timeout=5.0)
        server.destroy()
        mock.destroy_node()
        rclpy.try_shutdown()


def _serve(node: Node, case: str, events: list[str | tuple[str, bool]]) -> ActionServer:
    stop: Future[None] = Future()
    clock = node.create_publisher(Clock, "/clock", 10)
    tick = Clock()
    tick.clock.sec = 1
    tick.clock.nanosec = 0

    def step() -> None:
        elapsed, tick.clock.nanosec = divmod(tick.clock.nanosec + 100_000_000, 1_000_000_000)
        tick.clock.sec += elapsed
        clock.publish(tick)

    if case != "wall_timeout":
        node.create_timer(0.03, step)
    amcl_qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
    amcl = node.create_publisher(PoseWithCovarianceStamped, "/amcl_pose", amcl_qos)

    def localize(pose: PoseWithCovarianceStamped) -> None:
        events.append("pose")
        if case == "spawn_failed":
            pose.pose.pose.position.x += 1.0
        amcl.publish(pose)

    def start(_request: Trigger.Request, response: Trigger.Response) -> Trigger.Response:
        events.append("start")
        response.success = True
        return response

    def flush(request: SetBool.Request, response: SetBool.Response) -> SetBool.Response:
        events.append(("stop", request.data))
        response.success = True
        return response

    def cancel(_goal: ServerGoalHandle) -> CancelResponse:
        stop.set_result(None)
        return CancelResponse.ACCEPT

    async def navigate(goal: ServerGoalHandle) -> NavigateToPose.Result:
        events.append("goal")
        goal.publish_feedback(NavigateToPose.Feedback(number_of_recoveries=1))
        if case.endswith("timeout"):
            await stop
            goal.canceled()
        elif case == "success":
            goal.succeed()
        else:
            goal.abort()
        return NavigateToPose.Result()

    active = State.PRIMARY_STATE_ACTIVE
    amcl_id = State.PRIMARY_STATE_INACTIVE if case == "startup_timeout" else active
    node.create_service(
        GetState, "amcl/get_state", lambda _, _r: GetState.Response(current_state=State(id=amcl_id))
    )
    node.create_service(
        GetState,
        "bt_navigator/get_state",
        lambda _, _r: GetState.Response(
            current_state=State(id=active if "pose" in events else State.PRIMARY_STATE_INACTIVE)
        ),
    )
    node.create_subscription(PoseWithCovarianceStamped, "/initialpose", localize, 10)
    node.create_service(Trigger, "episode_recorder/start", start)
    node.create_service(SetBool, "episode_recorder/stop", flush)
    return ActionServer(node, NavigateToPose, "navigate_to_pose", navigate, cancel_callback=cancel)


def test_missing_episode_is_an_internal_error(tmp_path: Path) -> None:
    """Classify invalid input before producing an episode result."""
    missing = tmp_path / "episode.yaml"
    assert main(["--ros-args", "-p", f"episode_file:={missing}"]) == 12
    assert not (tmp_path / "episode_done.json").exists()
