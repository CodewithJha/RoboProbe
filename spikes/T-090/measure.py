"""Measure an actual Nav2 goal in the installed TurtleBot 4 warehouse."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import signal
import statistics
import subprocess
import tempfile
from pathlib import Path
from time import monotonic

import rclpy
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import PoseStamped
from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult
from rclpy.parameter import Parameter
from rclpy.qos import qos_profile_sensor_data
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import Image


def pose(x: float, y: float, yaw: float) -> PoseStamped:
    message = PoseStamped()
    message.header.frame_id = "map"
    message.pose.position.x = x
    message.pose.position.y = y
    message.pose.orientation.z = math.sin(yaw / 2)
    message.pose.orientation.w = math.cos(yaw / 2)
    return message


def stop_process(job: subprocess.Popen[bytes]) -> None:
    if job.poll() is not None:
        return
    os.killpg(job.pid, signal.SIGINT)
    try:
        job.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(job.pid, signal.SIGKILL)
        job.wait()


def deadline(_signum: int, _frame: object) -> None:
    raise TimeoutError("spike wall-clock limit reached")


def command(*cmd: str) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
    except subprocess.TimeoutExpired:
        return "timed out"
    return (result.stdout or result.stderr).strip()


def measure(args: argparse.Namespace) -> None:
    args.output.mkdir(parents=True, exist_ok=True)
    nav_share = Path(get_package_share_directory("nav2_bringup"))
    sim_share = Path(get_package_share_directory("nav2_minimal_tb4_sim"))
    original = (nav_share / "launch/tb4_simulation_launch.py").read_text()
    flag = re.compile(r"(['\"]-s['\"]\s*,\s*)(world_sdf\s*\])")
    adjusted, changes = flag.subn(r"\1'--headless-rendering', \2", original)
    if changes != 1 and "--headless-rendering" not in original:
        raise RuntimeError("could not find the Gazebo server arguments in the installed launch")
    args.output.joinpath("versions.txt").write_text(command("dpkg-query", "-W", "ros-jazzy-*"))
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(args.timeout)
    with tempfile.TemporaryDirectory() as temporary:
        custom_launch = Path(temporary) / "headless.launch.py"
        custom_launch.write_text(adjusted)
        launch_args = [
            "ros2",
            "launch",
            str(custom_launch),
            "headless:=True",
            "use_rviz:=False",
            f"world:={sim_share / 'worlds/warehouse.sdf'}",
            f"map:={nav_share / 'maps/warehouse.yaml'}",
            f"x_pose:={args.start_x}",
            f"y_pose:={args.start_y}",
            f"yaw:={args.yaw}",
        ]
        with (
            args.output.joinpath("launch.log").open("wb") as launch_log,
            args.output.joinpath("stats.txt").open("wb") as stats_log,
        ):
            began = monotonic()
            server = subprocess.Popen(
                launch_args, stdout=launch_log, stderr=subprocess.STDOUT, start_new_session=True
            )
            stats = None
            rclpy.init()
            nav = BasicNavigator()
            nav.set_parameters([Parameter("use_sim_time", value=True)])
            last_clock = None

            def observe_clock(message: Clock) -> None:
                nonlocal last_clock
                last_clock = message.clock.sec + message.clock.nanosec / 1e9

            nav.create_subscription(Clock, "/clock", observe_clock, qos_profile_sensor_data)
            try:
                nav.setInitialPose(pose(args.start_x, args.start_y, args.yaw))
                nav.waitUntilNav2Active()
                active_s = monotonic() - began
                print(f"Nav2 active after {active_s:.3f} s", flush=True)
                while last_clock is None:
                    rclpy.spin_once(nav, timeout_sec=0.1)
                topics = command("gz", "topic", "-l").splitlines()
                stats_topic = next((topic for topic in topics if topic.endswith("/stats")), None)
                if stats_topic:
                    stats = subprocess.Popen(
                        ["gz", "topic", "-e", "-t", stats_topic],
                        stdout=stats_log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                stamped = command(
                    "ros2", "param", "get", "/controller_server", "enable_stamped_cmd_vel"
                )
                clock_enabled = command(
                    "ros2", "param", "get", "/controller_server", "use_sim_time"
                )
                cameras = [
                    topic
                    for topic, _ in nav.get_topic_names_and_types()
                    if "image" in topic or "depth" in topic
                ]
                depth_frames = 0

                def observe_depth(_message: Image) -> None:
                    nonlocal depth_frames
                    depth_frames += 1

                depth_topic = next(
                    (topic for topic in cameras if "stereo" in topic or "depth" in topic), None
                )
                if depth_topic:
                    nav.create_subscription(
                        Image, depth_topic, observe_depth, qos_profile_sensor_data
                    )
                for _ in range(5):
                    rclpy.spin_once(nav, timeout_sec=0.05)
                if args.ready_dir is not None:
                    (args.ready_dir / f"{args.slot}.ready").touch()
                    while len(list(args.ready_dir.glob("*.ready"))) < args.participants:
                        rclpy.spin_once(nav, timeout_sec=0.1)
                goal = pose(args.goal_x, args.goal_y, args.yaw)
                goal.header.stamp = nav.get_clock().now().to_msg()
                sim_start = last_clock
                goal_start = monotonic()
                nav.goToPose(goal)
                while not nav.isTaskComplete():
                    pass
                goal_wall_s = monotonic() - goal_start
                assert last_clock is not None and sim_start is not None
                result = nav.getResult()
                if stats is not None:
                    stop_process(stats)
                    stats = None
                stats_log.flush()
                factors = [
                    float(value)
                    for value in re.findall(
                        r"real_time_factor:\s*([0-9.eE+-]+)",
                        args.output.joinpath("stats.txt").read_text(errors="replace"),
                    )
                ]
                summary = {
                    "startup_wall_s": active_s,
                    "goal_wall_s": goal_wall_s,
                    "goal_started_monotonic_s": goal_start,
                    "goal_sim_s": last_clock - sim_start,
                    "goal_result": result.name,
                    "action_clock_rtf": (last_clock - sim_start) / goal_wall_s,
                    "gazebo_stats_topic": stats_topic,
                    "gazebo_rtf_samples": factors,
                    "gazebo_rtf_median": statistics.median(factors) if factors else None,
                    "stamped_cmd_vel": stamped,
                    "use_sim_time": clock_enabled,
                    "camera_topics": cameras,
                    "depth_topic": depth_topic,
                    "depth_frames": depth_frames,
                    "software_rendering": os.environ.get("LIBGL_ALWAYS_SOFTWARE"),
                }
                args.output.joinpath("result.json").write_text(json.dumps(summary, indent=2) + "\n")
                print(json.dumps(summary), flush=True)
                if result != TaskResult.SUCCEEDED:
                    raise RuntimeError(f"NavigateToPose ended in {result.name}")
            finally:
                signal.alarm(0)
                if stats is not None:
                    stop_process(stats)
                stop_process(server)
                nav.destroy_node()
                rclpy.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--ready-dir", type=Path)
    parser.add_argument("--slot", type=int)
    parser.add_argument("--participants", type=int, default=1)
    parser.add_argument("--start-x", type=float, default=2.12)
    parser.add_argument("--start-y", type=float, default=-21.3)
    parser.add_argument("--goal-x", type=float, default=2.12)
    parser.add_argument("--goal-y", type=float, default=-19.3)
    parser.add_argument("--yaw", type=float, default=math.pi / 2)
    measure(parser.parse_args())
