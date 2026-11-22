"""Validate episode launch configuration before starting external processes (T-094d)."""

# ruff: noqa: S101

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from xml.dom import minidom

import pytest
from launch import LaunchContext
from launch.actions import EmitEvent, ExecuteProcess, RegisterEventHandler

if TYPE_CHECKING:
    from types import ModuleType

_MIN_PROCESS_ACTIONS = 2
_LAUNCH = Path(__file__).resolve().parents[1] / "launch" / "episode.launch.py"


@pytest.fixture
def launch_module() -> ModuleType:
    """Load the checked-in launch module without running the actions."""
    spec = importlib.util.spec_from_file_location("roboprobe_episode_launch", _LAUNCH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepared_episode(workdir: Path) -> LaunchContext:
    workdir.mkdir()
    (workdir / "world.sdf").write_text("<sdf version='1.9'/>", encoding="utf-8")
    (workdir / "nav2_params.yaml").write_text("{}", encoding="utf-8")
    (workdir / "bridge.yaml").write_text("[]", encoding="utf-8")
    (workdir / "perturb_params.yaml").write_text(
        "seeds: {perception_degrader: 123}\nperception_model_file: perception.yaml\n",
        encoding="utf-8",
    )
    (workdir / "perception.yaml").write_text("{}\n", encoding="utf-8")
    (workdir / "topics.yaml").write_text(
        "topics: {cmd_vel_nav: {name: /roboprobe/cmd_vel_nav}}", encoding="utf-8"
    )
    (workdir / "episode.yaml").write_text(
        "world_name: warehouse\nrobot_name: turtlebot4\nmap_file: map.yaml\n"
        "simulator_seed: 42\nsample_hz: 20.0\n"
        "start: {x: 2.12, y: -21.32, yaw: 1.57}\n",
        encoding="utf-8",
    )
    (workdir / "map.yaml").write_text("image: warehouse.pgm\n", encoding="utf-8")
    (workdir / "warehouse.pgm").write_bytes(b"P5\n1 1\n255\n\xff")
    context = LaunchContext()
    context.launch_configurations.update(
        {"workdir": str(workdir), "headless": "true", "use_sim_time": "true"}
    )
    return context


def test_builds_process_graph(
    launch_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Assemble the Gazebo and ROS action graph from the generated workdir."""
    workdir = tmp_path / "episode"
    context = _prepared_episode(workdir)
    model = tmp_path / "urdf/standard/turtlebot4.urdf.xacro"
    model.parent.mkdir(parents=True)
    model.write_text('<robot name="turtlebot4"/>', encoding="utf-8")
    monkeypatch.setattr(launch_module, "get_package_share_directory", lambda _: str(tmp_path))
    graph = launch_module._launch(context)
    assert any(isinstance(action, RegisterEventHandler) for action in graph)
    assert sum(isinstance(action, ExecuteProcess) for action in graph) >= _MIN_PROCESS_ACTIONS


def test_rejects_outside_workdir_map(launch_module: ModuleType, tmp_path: Path) -> None:
    """Disallow map images that resolve outside the supplied episode directory."""
    workdir = tmp_path / "episode"
    context = _prepared_episode(workdir)
    outside = tmp_path / "outside.pgm"
    outside.write_bytes(b"P5\n1 1\n255\n\xff")
    (workdir / "warehouse.pgm").unlink()
    (workdir / "warehouse.pgm").symlink_to(outside)
    with pytest.raises(ValueError, match="inside"):
        launch_module._launch(context)


def test_robot_has_model_scoped_ground_truth_publisher(
    launch_module: ModuleType, tmp_path: Path
) -> None:
    """Attach the measured Gazebo model pose output consumed by the ROS bridge."""
    model = tmp_path / "robot.urdf.xacro"
    model.write_text('<robot name="turtlebot4"/>', encoding="utf-8")
    xml = launch_module._robot_description(model, 20.0)
    document = minidom.parseString(xml)  # noqa: S318 - fixture is a local constant XML document.
    [plugin] = document.getElementsByTagName("plugin")
    assert plugin.getAttribute("name") == "gz::sim::systems::PosePublisher"
    assert "<publish_model_pose>true</publish_model_pose>" in xml
    assert "<use_pose_vector_msg>false</use_pose_vector_msg>" in xml
    assert "<update_frequency>20.0</update_frequency>" in xml


def test_simulator_exit_shuts_down_launch(launch_module: ModuleType) -> None:
    """Terminate the other nodes when the simulator exits before the episode manager."""
    events = launch_module._on_simulator_exit(SimpleNamespace(returncode=1), LaunchContext())
    assert len(events) == 1
    assert isinstance(events[0], EmitEvent)
