"""Capture a live map-frame Nav2 planner path (T-092)."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import rclpy
from geometry_msgs.msg import PoseStamped
from nav2_simple_commander.robot_navigator import BasicNavigator
from rclpy.parameter import Parameter


def _pose(nav: BasicNavigator, xyz: list[float]) -> PoseStamped:
    x, y, yaw = xyz
    pose = PoseStamped()
    pose.header.frame_id = "map"
    pose.header.stamp = nav.get_clock().now().to_msg()
    pose.pose.position.x = x
    pose.pose.position.y = y
    pose.pose.orientation.z = math.sin(yaw / 2)
    pose.pose.orientation.w = math.cos(yaw / 2)
    return pose


def main() -> None:
    """Request a path from the live planner using explicit start and goal poses."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", nargs=3, type=float, required=True, metavar=("X", "Y", "YAW"))
    parser.add_argument("--goal", nargs=3, type=float, required=True, metavar=("X", "Y", "YAW"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rclpy.init()
    nav = BasicNavigator(node_name="roboprobe_nominal_path")
    try:
        nav.set_parameters([Parameter("use_sim_time", value=True)])
        path = nav.getPath(_pose(nav, args.start), _pose(nav, args.goal), use_start=True)
        if path is None or not path.poses or path.header.frame_id != "map":
            msg = "the active Nav2 planner returned no usable map-frame path"
            raise RuntimeError(msg)
        points = [[round(p.pose.position.x, 6), round(p.pose.position.y, 6)] for p in path.poses]
        args.output.write_text(json.dumps(points, separators=(",", ":")) + "\n", encoding="utf-8")
    finally:
        nav.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
