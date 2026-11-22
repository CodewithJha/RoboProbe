"""Launch one materialised RoboProbe Gazebo episode (T-094d, FR-SIM-003)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import xacro
import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    AppendEnvironmentVariable,
    DeclareLaunchArgument,
    EmitEvent,
    ExecuteProcess,
    GroupAction,
    IncludeLaunchDescription,
    OpaqueFunction,
    RegisterEventHandler,
    SetEnvironmentVariable,
)
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, SetRemap
from launch_ros.parameter_descriptions import ParameterValue

if TYPE_CHECKING:
    from launch.action import Action
    from launch.events.process import ProcessExited
    from launch.launch_context import LaunchContext

_PACKAGE: Final = "roboprobe_ros"
# Stock pinned nav2_minimal_tb4_sim spawn height avoids intersecting the floor at birth.
_TB4_SPAWN_Z: Final = "0.01"


def _input(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        msg = f"expected episode file inside {root}: {name}"
        raise ValueError(msg)
    return path


def _yaml(path: Path) -> dict[str, Any]:
    value: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        msg = f"expected a YAML mapping in {path}"
        raise TypeError(msg)
    return {str(key): item for key, item in value.items()}


def _bool(context: LaunchContext, name: str) -> bool:
    result = LaunchConfiguration(name).perform(context).lower()
    if result not in {"true", "false", "1", "0"}:
        msg = f"{name} needs a boolean value"
        raise ValueError(msg)
    return result in {"true", "1"}


def _nav_launch(
    source: Path, parameters: Path, map_file: Path, use_sim_time: bool, delayed_command: str
) -> list[Action]:
    arguments = {
        "params_file": str(parameters),
        "map": str(map_file),
        "use_sim_time": str(use_sim_time).lower(),
        "autostart": "true",
        "use_composition": "False",
    }
    return [
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(source / "localization_launch.py")),
            launch_arguments=arguments.items(),
        ),
        GroupAction(
            actions=[
                # Docking publishes the normal final velocity topic directly.
                # Collision monitor already uses the separate delayed topic from its YAML.
                SetRemap(src="/cmd_vel", dst=delayed_command),
                IncludeLaunchDescription(
                    PythonLaunchDescriptionSource(str(source / "navigation_launch.py")),
                    launch_arguments=arguments.items(),
                ),
            ]
        ),
    ]


def _robot_description(model: Path, sample_hz: float) -> str:
    robot = xacro.process_file(str(model))
    gazebo = robot.createElement("gazebo")
    publisher = robot.createElement("plugin")
    publisher.setAttribute("filename", "gz-sim-pose-publisher-system")
    publisher.setAttribute("name", "gz::sim::systems::PosePublisher")
    for key, value in (
        ("publish_model_pose", "true"),
        ("publish_link_pose", "false"),
        ("publish_collision_pose", "false"),
        ("publish_visual_pose", "false"),
        ("publish_sensor_pose", "false"),
        ("publish_nested_model_pose", "false"),
        ("use_pose_vector_msg", "false"),
        ("update_frequency", str(sample_hz)),
    ):
        parameter = robot.createElement(key)
        parameter.appendChild(robot.createTextNode(value))
        publisher.appendChild(parameter)
    gazebo.appendChild(publisher)
    robot.documentElement.appendChild(gazebo)
    return str(robot.toxml())


def _on_simulator_exit(event: ProcessExited, context: LaunchContext) -> list[Action]:
    if context.is_shutdown:
        return []
    return [
        EmitEvent(
            event=Shutdown(reason=f"Gazebo exited before the episode ended ({event.returncode})")
        )
    ]


def _sim_actions(
    root: Path, world: Path, episode: dict[str, Any], use_sim_time: bool, headless: bool
) -> list[Action]:
    sim = Path(get_package_share_directory("nav2_minimal_tb4_sim"))
    description = Path(get_package_share_directory("nav2_minimal_tb4_description"))
    model = description / "urdf/standard/turtlebot4.urdf.xacro"
    payloads = Path(get_package_share_directory(_PACKAGE)) / "models"
    start = episode["start"]
    gazebo = ["gz", "sim", "-r", "--seed", str(episode["simulator_seed"])]
    if headless:
        gazebo.extend(["-s", "--headless-rendering"])

    simulator = ExecuteProcess(cmd=[*gazebo, str(world)], cwd=str(root), output="screen")
    return [
        AppendEnvironmentVariable("GZ_SIM_RESOURCE_PATH", str(sim / "worlds")),
        AppendEnvironmentVariable("GZ_SIM_RESOURCE_PATH", str(description.parent)),
        AppendEnvironmentVariable("GZ_SIM_RESOURCE_PATH", str(payloads)),
        RegisterEventHandler(OnProcessExit(target_action=simulator, on_exit=_on_simulator_exit)),
        simulator,
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            output="screen",
            parameters=[
                {
                    "use_sim_time": use_sim_time,
                    "robot_description": ParameterValue(
                        _robot_description(model, float(episode["sample_hz"])), value_type=str
                    ),
                }
            ],
        ),
        Node(
            package="ros_gz_sim",
            executable="create",
            output="screen",
            arguments=[
                "-world",
                str(episode["world_name"]),
                "-entity",
                str(episode["robot_name"]),
                "-topic",
                "robot_description",
                "-x",
                str(start["x"]),
                "-y",
                str(start["y"]),
                "-z",
                _TB4_SPAWN_Z,
                "-Y",
                str(start["yaw"]),
            ],
            parameters=[{"use_sim_time": use_sim_time}],
        ),
    ]


def _launch(context: LaunchContext) -> list[Action]:
    root = Path(LaunchConfiguration("workdir").perform(context)).resolve(strict=True)
    bridge = _input(root, "bridge.yaml")
    world = _input(root, "world.sdf")
    nav2 = _input(root, "nav2_params.yaml")
    topics_file = _input(root, "topics.yaml")
    perturb_file = _input(root, "perturb_params.yaml")
    episode_file = _input(root, "episode.yaml")
    episode = _yaml(episode_file)
    map_file = _input(root, episode["map_file"])
    map_image = _yaml(map_file)["image"]
    _input(root, str(map_file.parent.relative_to(root) / map_image))
    topics = _yaml(topics_file)["topics"]
    perturb = _yaml(perturb_file)
    _input(root, perturb["perception_model_file"])
    use_sim_time = _bool(context, "use_sim_time")

    shared = {
        "topics_file": str(topics_file),
        "perturb_file": str(perturb_file),
        "use_sim_time": use_sim_time,
    }
    manager = Node(
        package=_PACKAGE,
        executable="episode_manager",
        cwd=str(root),
        output="screen",
        parameters=[{**shared, "episode_file": str(episode_file)}],
    )
    relays = [
        Node(
            package=_PACKAGE,
            executable=name,
            cwd=str(root),
            output="screen",
            parameters=[shared, overrides],
        )
        for name, overrides in (
            ("sensor_perturber", {}),
            ("perception_degrader", {"seed": int(perturb["seeds"]["perception_degrader"])}),
            ("cmd_delay", {}),
            ("episode_recorder", {"episode_file": str(episode_file)}),
        )
    ]
    nav_source = Path(get_package_share_directory("nav2_bringup")) / "launch"
    return [
        SetEnvironmentVariable("ROS_LOG_DIR", str(root / "ros-logs")),
        RegisterEventHandler(
            OnProcessExit(
                target_action=manager,
                on_exit=[EmitEvent(event=Shutdown(reason="RoboProbe episode finished"))],
            )
        ),
        *_sim_actions(root, world, episode, use_sim_time, _bool(context, "headless")),
        Node(
            package="ros_gz_bridge",
            executable="parameter_bridge",
            output="screen",
            parameters=[{"config_file": str(bridge), "use_sim_time": use_sim_time}],
        ),
        *_nav_launch(nav_source, nav2, map_file, use_sim_time, topics["cmd_vel_nav"]["name"]),
        *relays,
        manager,
    ]


def generate_launch_description() -> LaunchDescription:
    """Launch Gazebo, its bridge, Nav2 and the nodes for one isolated episode."""
    return LaunchDescription(
        [
            DeclareLaunchArgument("workdir", description="Materialised episode directory"),
            DeclareLaunchArgument("headless", default_value="true"),
            DeclareLaunchArgument("use_sim_time", default_value="true"),
            OpaqueFunction(function=_launch),
        ]
    )
