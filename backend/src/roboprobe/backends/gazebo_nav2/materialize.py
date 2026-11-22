"""Create the deterministic Gazebo episode inputs (T-096a, FR-SIM-003, FR-SCN-005)."""

from __future__ import annotations

import importlib
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from roboprobe.backends.base import MaterializedScenario
from roboprobe.backends.gazebo_nav2.nav2_params import Nav2ParamOverlay, PatchedNav2Params
from roboprobe.backends.gazebo_nav2.sdf import PalletPlacement, SdfPatcher
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.core.seeding import PERCEPTION, SENSOR, SIMULATOR, derive_seed
from roboprobe.core.settings.backends import GazeboNav2Settings
from roboprobe.core.settings.oracles import InfraThresholds
from roboprobe.core.settings.worker import WorkerSettings
from roboprobe.core.types import Scenario, SutProfile, TaskSpec
from roboprobe.perturbation.perception import PerceptionModel
from roboprobe.scenario._documents import load_yaml_document, read_document
from roboprobe.scenario.materialize import place_obstacle, render_template, side_sign
from roboprobe.scenario.repo_root import discover_repo_root
from roboprobe.scenario.sut_profile import GazeboNav2ProfileConfig
from roboprobe.scenario.task import load_nominal_path, polyline_length_m, time_limit_s

__all__ = ["EpisodeSeeds", "GazeboMaterializer", "MaterializedEpisode"]

MaterializedEpisode = MaterializedScenario
_BACKEND = "gazebo_nav2"
_STOCK_PARAMS = GazeboNav2Settings().base_nav2_params
_MAP_YAML = "map.yaml"
_MAP_IMAGE = "map.pgm"
_PERCEPTION_FILE = "perception_model.yaml"
_WORLD_ROBOT = "turtlebot4"
_MIN_PACKAGE_PATH_PARTS = 2
# Gazebo Harmonic's CLI passes the seed through a signed C int.
_GAZEBO_CLI_MAX_SEED = (1 << 31) - 1
_GZ_TO_ROS = "GZ_TO_ROS"
_ROS_TO_GZ = "ROS_TO_GZ"
_STOCK_BRIDGES = (
    ("clock", "/clock", "rosgraph_msgs/msg/Clock", "gz.msgs.Clock", _GZ_TO_ROS),
    ("joint_states", "joint_states", "sensor_msgs/msg/JointState", "gz.msgs.Model", _GZ_TO_ROS),
    ("tf", "/tf", "tf2_msgs/msg/TFMessage", "gz.msgs.Pose_V", _GZ_TO_ROS),
    ("imu", "/imu", "sensor_msgs/msg/Imu", "gz.msgs.IMU", _GZ_TO_ROS),
)
_BRIDGE_TEMPLATE = """{% for ros_name, gz_name, ros_type, gz_type, direction in entries -%}
- ros_topic_name: {{ ros_name | tojson }}
  gz_topic_name: {{ gz_name | tojson }}
  ros_type_name: {{ ros_type | tojson }}
  gz_type_name: {{ gz_type | tojson }}
  direction: {{ direction }}
{% endfor -%}
"""


@dataclass(frozen=True, slots=True)
class EpisodeSeeds:
    """Root run seed for deterministic Gazebo and ROS node streams."""

    run: int


class _Topic(BaseModel):
    name: str
    type: str


class _Topics(BaseModel):
    stamped_cmd_vel: bool
    topics: dict[str, _Topic]
    frames: dict[str, str]

    def entry(self, name: str) -> _Topic:
        """Return a required topic and its message type."""
        try:
            return self.topics[name]
        except KeyError as exc:
            msg = f"Gazebo topics catalog is missing {name}"
            raise ValidationError(msg) from exc


def _find_package(name: str) -> Path:
    try:
        index = importlib.import_module("ament_index_python.packages")
        return Path(index.get_package_share_directory(name))
    except (ImportError, LookupError) as exc:
        msg = f"cannot locate ROS package {name}; source the ROS environment first"
        raise NotFoundError(msg, context={"package": name}) from exc


def _package_path(reference: str, resolver: Callable[[str], Path]) -> Path:
    path = Path(reference)
    if path.is_absolute():
        return path
    if len(path.parts) < _MIN_PACKAGE_PATH_PARTS or ".." in path.parts:
        msg = f"expected an absolute path or ROS package-relative file, got {reference}"
        raise ValidationError(msg)
    package, *relative = path.parts
    share = resolver(package).resolve()
    resolved = share.joinpath(*relative).resolve()
    if not resolved.is_relative_to(share):
        msg = f"ROS package asset escapes its package: {reference}"
        raise ValidationError(msg)
    return resolved


def _number(scenario: Scenario, key: str) -> float:
    value = scenario.values.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        msg = f"Gazebo scenario requires a finite number for {key}"
        raise ValidationError(msg)
    return float(value)


def _read_topics(raw: bytes, path: Path) -> _Topics:
    try:
        topics = _Topics.model_validate(load_yaml_document(raw, source=str(path)))
    except PydanticValidationError as exc:
        msg = f"{path}: invalid Gazebo topics catalog"
        raise ValidationError(msg) from exc
    for raw_name, processed_name in (
        ("scan_raw", "scan"),
        ("depth_points_raw", "depth_points"),
        ("cmd_vel", "cmd_vel_nav"),
    ):
        upstream, downstream = topics.entry(raw_name), topics.entry(processed_name)
        if upstream.name == downstream.name or upstream.type != downstream.type:
            msg = (
                f"Gazebo {raw_name} and {processed_name} require distinct names and matching types"
            )
            raise ValidationError(msg)
    twist = "TwistStamped" if topics.stamped_cmd_vel else "Twist"
    if not topics.frames.get("map"):
        msg = "Gazebo topics catalog requires frames.map"
        raise ValidationError(msg)
    for name, expected in (
        ("scan_raw", "sensor_msgs/msg/LaserScan"),
        ("depth_points_raw", "sensor_msgs/msg/PointCloud2"),
        ("cmd_vel", f"geometry_msgs/msg/{twist}"),
        ("odom", "nav_msgs/msg/Odometry"),
        ("initial_pose", "geometry_msgs/msg/PoseWithCovarianceStamped"),
        ("ground_truth_pose", "geometry_msgs/msg/PoseStamped"),
    ):
        if topics.entry(name).type != expected:
            msg = f"Gazebo {name} requires the ROS message type {expected}"
            raise ValidationError(msg)
    return topics


def _bridge(topics: _Topics, world: str) -> str:
    bindings = (
        ("odom", "/odom", "gz.msgs.Odometry", _GZ_TO_ROS),
        ("scan_raw", "/scan", "gz.msgs.LaserScan", _GZ_TO_ROS),
        ("depth_points_raw", "/rgbd_camera/points", "gz.msgs.PointCloudPacked", _GZ_TO_ROS),
        ("cmd_vel", "/cmd_vel", "gz.msgs.Twist", _ROS_TO_GZ),
        (
            "ground_truth_pose",
            f"/world/{world}/model/{_WORLD_ROBOT}/pose",
            "gz.msgs.Pose",
            _GZ_TO_ROS,
        ),
    )
    entries = list(_STOCK_BRIDGES)
    for key, gz_topic, gz_type, direction in bindings:
        topic = topics.entry(key)
        entries.append((topic.name, gz_topic, topic.type, gz_type, direction))
    return render_template(_BRIDGE_TEMPLATE, {"entries": entries})


def _map_assets(root: Path, reference: str) -> tuple[bytes, bytes]:
    path = (root / reference).resolve()
    if not path.is_file():
        path = (root / "tasks" / reference).resolve()
    if not path.is_relative_to(root):
        msg = "Gazebo task map must stay inside the repository"
        raise ValidationError(msg)
    map_config = load_yaml_document(read_document(path), source=str(path))
    if not isinstance(map_config, dict) or not isinstance(map_config.get("image"), str):
        msg = f"{path}: Gazebo task map requires a PGM image"
        raise ValidationError(msg)
    image = (path.parent / map_config["image"]).resolve()
    if not image.is_relative_to(path.parent):
        msg = f"{path}: Gazebo map image must stay inside the map directory"
        raise ValidationError(msg)
    map_config["image"] = _MAP_IMAGE
    map_image = read_document(image)
    if not map_image.startswith(b"P5"):
        msg = f"{path}: Gazebo task map requires a binary PGM image"
        raise ValidationError(msg)
    return yaml.safe_dump(map_config, sort_keys=True).encode(), map_image


class GazeboMaterializer:
    """Materialize launch files so the ROS side only needs the episode workdir."""

    def __init__(  # noqa: PLR0913 - typed episode-adapter boundary plus test/package overrides
        self,
        settings: GazeboNav2Settings,
        sut: SutProfile,
        task: TaskSpec,
        *,
        resolve_package: Callable[[str], Path] = _find_package,
        repo_root: Path | None = None,
        wall_timeout_s: float | None = None,
        spawn_tolerance_m: float | None = None,
    ) -> None:
        """Validate configuration and retain host asset location for deterministic generation."""
        if sut.backend != _BACKEND:
            msg = "Gazebo materializer requires a gazebo_nav2 SUT profile"
            raise ValidationError(msg)
        if task.provisional:
            msg = "Gazebo materializer requires a verified task with no provisional values"
            raise ValidationError(msg)
        try:
            self._profile = GazeboNav2ProfileConfig.model_validate(sut.config)
        except PydanticValidationError as exc:
            msg = "Gazebo materializer requires valid Nav2 SUT parameters"
            raise ValidationError(msg) from exc
        self._settings = settings
        self._task = task
        self._root = (repo_root or discover_repo_root()).resolve()
        self._resolve_package = resolve_package
        self._wall_timeout_s = (
            WorkerSettings().default_wall_timeout_s if wall_timeout_s is None else wall_timeout_s
        )
        self._spawn_tolerance_m = (
            InfraThresholds().spawn_tolerance_m if spawn_tolerance_m is None else spawn_tolerance_m
        )

    def materialize(
        self, scenario: Scenario, workdir: Path, seeds: EpisodeSeeds
    ) -> MaterializedEpisode:
        """Resolve scenario mechanisms, then write deterministic launch files."""
        settings = self._settings
        task_root = self._root / "tasks"
        task_file = (task_root / f"{self._task.id}.yaml").resolve()
        if task_file.parent != task_root:
            msg = "Gazebo task id must resolve inside the task directory"
            raise ValidationError(msg)
        nominal = load_nominal_path(task_file, self._task)
        pallets = tuple(
            PalletPlacement(
                obstacle.model,
                place_obstacle(
                    nominal,
                    _number(scenario, obstacle.placement.along),
                    _number(scenario, obstacle.placement.lateral),
                    side_sign(obstacle.placement.side),
                ),
                obstacle.size[2],
            )
            for obstacle in self._task.injected_obstacles
        )
        model_path = self._root / settings.perception_model_file
        model = PerceptionModel.from_yaml(model_path)
        illuminance = _number(scenario, "env.illuminance")
        speed = _number(scenario, "robot.max_speed")
        world_path = _package_path(settings.base_world, self._resolve_package)
        world = SdfPatcher(world_path).patch(
            lighting_scale=min(1.0, illuminance / model.l_ref_lux),
            floor_friction=_number(scenario, "env.floor_friction"),
            real_time_factor=settings.physics.real_time_factor,
            pallets=pallets,
        )
        topics_path = self._root / settings.topics_file
        topics_raw = read_document(topics_path)
        topics = _read_topics(topics_raw, topics_path)
        params = self._nav2(topics, speed)
        map_yaml, map_image = _map_assets(self._root, self._task.map)
        time_limit = time_limit_s(self._task, speed, polyline_length_m(nominal))
        simulator_seed = derive_seed(seeds.run, SIMULATOR) & _GAZEBO_CLI_MAX_SEED
        files = {
            "world.sdf": world.content,
            "nav2_params.yaml": params.content.encode(),
            "perturb_params.yaml": self._perturb(
                scenario, seeds, illuminance, params.controller_frequency_hz
            ).encode(),
            "bridge.yaml": _bridge(topics, world.name).encode(),
            "episode.yaml": self._episode(
                pallets, params, time_limit, simulator_seed, world.name
            ).encode(),
            "topics.yaml": topics_raw,
            _MAP_YAML: map_yaml,
            _MAP_IMAGE: map_image,
            _PERCEPTION_FILE: read_document(model_path),
        }
        workdir.mkdir(parents=True, exist_ok=True)
        written: dict[str, Path] = {}
        for filename, content in files.items():
            output = workdir / filename
            output.write_bytes(content)
            written[filename] = output
        return MaterializedEpisode(
            files=written, payload={"time_limit_s": time_limit, "simulator_seed": simulator_seed}
        )

    def _nav2(self, topics: _Topics, speed: float) -> PatchedNav2Params:
        reference = self._profile.base_nav2_params
        if reference == _STOCK_PARAMS:
            reference = self._settings.base_nav2_params
        return Nav2ParamOverlay(
            _package_path(reference, self._resolve_package), self._profile
        ).patch(
            speed_mps=speed,
            depth_topic=topics.entry("depth_points").name,
            command_output_topic=topics.entry("cmd_vel_nav").name,
            stamped_cmd_vel=topics.stamped_cmd_vel,
        )

    def _perturb(
        self, scenario: Scenario, seeds: EpisodeSeeds, illuminance: float, rate: float
    ) -> str:
        sensor_seed = derive_seed(seeds.run, SENSOR)
        return yaml.safe_dump(
            {
                "illuminance_lux": illuminance,
                "perception_model_file": _PERCEPTION_FILE,
                "lidar": {
                    "sigma_m": _number(scenario, "sensor.lidar_noise_std"),
                    "dropout_p": _number(scenario, "sensor.lidar_dropout"),
                },
                "cmd_delay_ms": _number(scenario, "comms.cmd_delay_ms"),
                "rate_hz": rate,
                "seed": sensor_seed,
                "seeds": {
                    "sensor_perturber": sensor_seed,
                    "perception_degrader": derive_seed(seeds.run, PERCEPTION),
                    "cmd_delay": derive_seed(seeds.run, SIMULATOR, "cmd_delay"),
                },
            },
            sort_keys=True,
        )

    def _episode(
        self,
        pallets: tuple[PalletPlacement, ...],
        params: PatchedNav2Params,
        time_limit: float,
        simulator_seed: int,
        world_name: str,
    ) -> str:
        return yaml.safe_dump(
            {
                "start": self._task.start.model_dump(mode="json"),
                "goal": self._task.goal.model_dump(mode="json"),
                "time_limit_s": time_limit,
                "sample_hz": self._settings.sample_hz,
                "record_bag": self._settings.record_bag,
                "startup_timeout_s": self._settings.startup_timeout_s,
                "teardown_grace_s": self._settings.teardown_grace_s,
                "spawn_tolerance_m": self._spawn_tolerance_m,
                "wall_timeout_factor": self._wall_timeout_s / time_limit,
                "map_file": _MAP_YAML,
                "world_name": world_name,
                "robot_name": _WORLD_ROBOT,
                "footprint": params.footprint,
                "simulator_seed": simulator_seed,
                "pallets": [
                    {"pose": pallet.pose.model_dump(mode="json"), "size": list(obstacle.size)}
                    for pallet, obstacle in zip(pallets, self._task.injected_obstacles, strict=True)
                ],
            },
            sort_keys=True,
        )
