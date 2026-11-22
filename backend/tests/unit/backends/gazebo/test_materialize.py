"""Gazebo launch-file generation and input validation (T-096a)."""

from pathlib import Path
from xml.etree import ElementTree

import pytest
import yaml

from roboprobe.backends.gazebo_nav2.materialize import EpisodeSeeds, GazeboMaterializer
from roboprobe.backends.gazebo_nav2.nav2_params import Nav2ParamOverlay
from roboprobe.backends.gazebo_nav2.sdf import PalletPlacement, SdfPatcher
from roboprobe.core.errors import ValidationError
from roboprobe.core.settings.backends import GazeboNav2Settings
from roboprobe.core.types import Pose2D, Scenario, TaskSpec
from roboprobe.scenario.sut_profile import GazeboNav2ProfileConfig, load_sut_profile

pytestmark = pytest.mark.unit

BASE_WORLD = """<sdf version="1.7">
  <world name="warehouse">
    <physics name="test" type="ode"><real_time_factor>1</real_time_factor></physics>
    <scene><ambient>0.8 0.6 0.4 1</ambient></scene>
    <light name="sun" type="directional"><diffuse>1 0.8 0.6 1</diffuse></light>
    <light name="lamp" type="point"><diffuse>1 1 1 0.8</diffuse></light>
    <model name="ground_plane">
      <link name="link">
        <collision name="collision"><geometry><plane /></geometry></collision>
      </link>
    </model>
  </world>
</sdf>
"""

BASE_PARAMS = {
    "controller_server": {
        "ros__parameters": {"controller_frequency": 20.0, "FollowPath": {"vx_max": 0.5}}
    },
    "velocity_smoother": {"ros__parameters": {"max_velocity": [0.5, 0.0, 2.0]}},
    "local_costmap": {
        "local_costmap": {
            "ros__parameters": {
                "robot_radius": 0.22,
                "plugins": ["voxel_layer", "inflation_layer"],
                "voxel_layer": {
                    "enabled": False,
                    "observation_sources": "scan",
                    "scan": {"topic": "/scan"},
                },
            }
        }
    },
    "collision_monitor": {"ros__parameters": {"cmd_vel_out_topic": "/cmd_vel"}},
}
SPEED_PATHS = (
    "controller_server.ros__parameters.FollowPath.vx_max",
    "velocity_smoother.ros__parameters.max_velocity[0]",
)
ROOT = Path(__file__).resolve().parents[5]
FIXTURES = ROOT / "backend/tests/fixtures/gazebo_materialize"
VALUES = {
    "robot.max_speed": 0.4,
    "obstacle.clearance": 0.5,
    "env.illuminance": 150.0,
    "sensor.lidar_noise_std": 0.01,
    "env.floor_friction": 0.5,
    "comms.cmd_delay_ms": 50.0,
    "obstacle.along_path": 0.5,
    "sensor.lidar_dropout": 0.04,
}


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    root = tmp_path / "inputs"
    for folder in ("tasks/paths", "map", "nav2", "sim"):
        (root / folder).mkdir(parents=True)
    (root / "map/model.pgm").write_bytes(b"P5\n2 2\n255\n" + bytes([0, 255, 255, 0]))
    (root / "map/model.yaml").write_text("image: model.pgm\nresolution: 0.05\n", encoding="utf-8")
    (root / "tasks/paths/nominal.csv").write_text("x,y\n0,0\n10,0\n", encoding="utf-8")
    (root / "sim/world.sdf").write_text(BASE_WORLD, encoding="utf-8")
    (root / "nav2/params.yaml").write_text(yaml.safe_dump(BASE_PARAMS), encoding="utf-8")
    topics = {
        "scan_raw": ("/scan_raw", "sensor_msgs/msg/LaserScan"),
        "scan": ("/scan", "sensor_msgs/msg/LaserScan"),
        "depth_points_raw": ("/rgbd_camera/points_raw", "sensor_msgs/msg/PointCloud2"),
        "depth_points": ("/rgbd_camera/points", "sensor_msgs/msg/PointCloud2"),
        "odom": ("/odom", "nav_msgs/msg/Odometry"),
        "initial_pose": ("/initialpose", "geometry_msgs/msg/PoseWithCovarianceStamped"),
        "cmd_vel": ("/cmd_vel", "geometry_msgs/msg/Twist"),
        "cmd_vel_nav": ("/roboprobe/cmd_vel_nav", "geometry_msgs/msg/Twist"),
        "ground_truth_pose": ("/ground_truth_pose", "geometry_msgs/msg/PoseStamped"),
    }
    catalog = {
        "stamped_cmd_vel": False,
        "frames": {"map": "map"},
        "topics": {key: {"name": name, "type": kind} for key, (name, kind) in topics.items()},
    }
    (root / "topics.yaml").write_text(yaml.safe_dump(catalog), encoding="utf-8")
    return root


@pytest.fixture
def materializer(source_tree: Path) -> GazeboMaterializer:
    task = TaskSpec.model_validate(
        {
            "id": "warehouse",
            "schema_version": 1,
            "world": {"gazebo": "sim/world.sdf"},
            "map": "map/model.yaml",
            "start": {"x": 0, "y": 0, "yaw": 0},
            "goal": {"x": 10, "y": 0, "yaw": 0},
            "goal_tolerance": {"xy": 0.25, "yaw": 0.5},
            "nominal_path": "paths/nominal.csv",
            "time_limit": {"factor": 2, "cap_s": 100, "offset_s": 5},
            "injected_obstacles": [
                {
                    "model": "dropped_pallet",
                    "size": [0.8, 0.6, 0.135],
                    "placement": {
                        "along": "obstacle.along_path",
                        "lateral": "obstacle.clearance",
                        "side": "left",
                    },
                },
            ],
        }
    )
    sut = load_sut_profile(ROOT / "configs/sut_profiles/tb4_nav2_default.yaml", strict=True)
    return GazeboMaterializer(
        GazeboNav2Settings(
            base_world="sim/world.sdf",
            base_nav2_params="nav2/params.yaml",
            topics_file=Path("topics.yaml"),
            perception_model_file=ROOT / "configs/perception/oakd_lowlight_v1.yaml",
            sample_hz=15,
            record_bag="always",
        ),
        sut,
        task,
        repo_root=source_tree,
        resolve_package=lambda package: source_tree / package,
        wall_timeout_s=220,
        spawn_tolerance_m=0.25,
    )


def _scenario(**overrides: float) -> Scenario:
    return Scenario(
        space_id="warehouse",
        space_version="0123456789ab",
        scenario_hash="0123456789abcdef",
        values={**VALUES, **overrides},
    )


def test_materializes_golden_launch_files(
    materializer: GazeboMaterializer, source_tree: Path, tmp_path: Path
) -> None:
    episode = materializer.materialize(_scenario(), tmp_path / "first", EpisodeSeeds(run=51))
    repeated = materializer.materialize(_scenario(), tmp_path / "again", EpisodeSeeds(run=51))
    for name in (
        "world.sdf",
        "episode.yaml",
        "perturb_params.yaml",
        "nav2_params.yaml",
        "bridge.yaml",
    ):
        assert episode.files[name].read_bytes() == (FIXTURES / name).read_bytes()
        assert repeated.files[name].read_bytes() == episode.files[name].read_bytes()
    assert episode.files["map.pgm"].read_bytes() == (source_tree / "map/model.pgm").read_bytes()
    assert (
        yaml.safe_load(episode.files["map.yaml"].read_text(encoding="utf-8"))["image"] == "map.pgm"
    )
    assert episode.payload["time_limit_s"] == 55.0
    captured = yaml.safe_load(episode.files["episode.yaml"].read_bytes())
    assert captured["simulator_seed"] == episode.payload["simulator_seed"]
    assert 0 <= captured["simulator_seed"] <= (1 << 31) - 1


def _changed_yaml_keys(left: object, right: object, prefix: str) -> set[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        return {
            changed
            for key in left.keys() | right.keys()
            for changed in _changed_yaml_keys(left.get(key), right.get(key), f"{prefix}.{key}")
        }
    return set() if left == right else {prefix}


def _changed_fields(name: str, first: Path, second: Path) -> set[str]:
    if first.read_bytes() == second.read_bytes():
        return set()
    if name == "world.sdf":
        left = ElementTree.parse(first)  # noqa: S314 - generated by the restricted SDF parser
        right = ElementTree.parse(second)  # noqa: S314 - generated by the restricted SDF parser
        pairs = zip(left.iter(), right.iter(), strict=True)
        return {
            f"{name}.{before.tag}"
            for before, after in pairs
            if before.text != after.text or before.attrib != after.attrib
        }
    assert name.endswith(".yaml"), name
    return _changed_yaml_keys(
        yaml.safe_load(first.read_bytes()), yaml.safe_load(second.read_bytes()), name
    )


@pytest.mark.parametrize(
    ("parameter", "value", "expected"),
    [
        (
            "robot.max_speed",
            0.5,
            {
                "nav2_params.yaml.controller_server.ros__parameters.FollowPath.vx_max",
                "nav2_params.yaml.velocity_smoother.ros__parameters.max_velocity",
                "episode.yaml.time_limit_s",
                "episode.yaml.wall_timeout_factor",
            },
        ),
        ("obstacle.clearance", 0.7, {"world.sdf.pose", "episode.yaml.pallets"}),
        (
            "env.illuminance",
            350.0,
            {"world.sdf.ambient", "world.sdf.diffuse", "perturb_params.yaml.illuminance_lux"},
        ),
        ("sensor.lidar_noise_std", 0.02, {"perturb_params.yaml.lidar.sigma_m"}),
        ("env.floor_friction", 0.8, {"world.sdf.mu", "world.sdf.mu2"}),
        ("comms.cmd_delay_ms", 90.0, {"perturb_params.yaml.cmd_delay_ms"}),
        ("obstacle.along_path", 0.6, {"world.sdf.pose", "episode.yaml.pallets"}),
        ("sensor.lidar_dropout", 0.08, {"perturb_params.yaml.lidar.dropout_p"}),
    ],
)
def test_parameter_changes_are_isolated(
    materializer: GazeboMaterializer,
    tmp_path: Path,
    parameter: str,
    value: float,
    expected: set[str],
) -> None:
    before = materializer.materialize(_scenario(), tmp_path / "before", EpisodeSeeds(run=51))
    after = materializer.materialize(
        _scenario(**{parameter: value}), tmp_path / "after", EpisodeSeeds(run=51)
    )
    assert {
        field
        for name, path in before.files.items()
        for field in _changed_fields(name, path, after.files[name])
    } == expected


@pytest.mark.parametrize(
    "case",
    [
        ("topics.yaml", "topics: {}", "invalid Gazebo topics catalog"),
        (
            "topics.yaml",
            "stamped_cmd_vel: false\nframes: {map: map}\ntopics: {}",
            "missing scan_raw",
        ),
        ("map/model.yaml", "image: ../elsewhere.pgm", "stay inside the map directory"),
        ("map/model.yaml", "resolution: 0.05", "requires a PGM image"),
        ("map/model.pgm", "invalid image", "requires a binary PGM image"),
    ],
)
def test_invalid_inputs_do_not_create_launch_files(
    materializer: GazeboMaterializer,
    source_tree: Path,
    tmp_path: Path,
    case: tuple[str, str, str],
) -> None:
    filename, contents, problem = case
    (source_tree / filename).write_text(contents, encoding="utf-8")
    output = tmp_path / "failed"
    with pytest.raises(ValidationError, match=problem):
        materializer.materialize(_scenario(), output, EpisodeSeeds(run=51))
    assert not output.exists()


def test_velocity_bridge_supports_consistent_stamped_mode(
    materializer: GazeboMaterializer, source_tree: Path, tmp_path: Path
) -> None:
    catalog_file = source_tree / "topics.yaml"
    catalog = yaml.safe_load(catalog_file.read_bytes())
    catalog["stamped_cmd_vel"] = True
    for role in ("cmd_vel", "cmd_vel_nav"):
        catalog["topics"][role]["type"] = "geometry_msgs/msg/TwistStamped"
    catalog_file.write_bytes(yaml.safe_dump(catalog).encode())
    episode = materializer.materialize(_scenario(), tmp_path / "stamped", EpisodeSeeds(run=51))
    bridge = yaml.safe_load(episode.files["bridge.yaml"].read_bytes())
    command = next(route for route in bridge if route["direction"] == "ROS_TO_GZ")
    assert command["ros_type_name"] == "geometry_msgs/msg/TwistStamped"
    nav2 = yaml.safe_load(episode.files["nav2_params.yaml"].read_bytes())
    collision = nav2["collision_monitor"]["ros__parameters"]
    assert collision["enable_stamped_cmd_vel"] is True
    assert collision["cmd_vel_out_topic"] == "/roboprobe/cmd_vel_nav"


def test_depth_topic_must_use_verified_cloud_type(
    materializer: GazeboMaterializer, source_tree: Path, tmp_path: Path
) -> None:
    catalog_file = source_tree / "topics.yaml"
    catalog = yaml.safe_load(catalog_file.read_bytes())
    for role in ("depth_points", "depth_points_raw"):
        catalog["topics"][role]["type"] = "sensor_msgs/msg/Image"
    catalog_file.write_bytes(yaml.safe_dump(catalog).encode())
    with pytest.raises(ValidationError, match=r"requires the ROS message type .*PointCloud2"):
        materializer.materialize(_scenario(), tmp_path / "invalid", EpisodeSeeds(run=51))


def test_nav2_overlays_speed_values_and_keeps_scan(tmp_path: Path) -> None:
    source = tmp_path / "nav2.yaml"
    source.write_text(yaml.safe_dump(BASE_PARAMS), encoding="utf-8")
    profile = GazeboNav2ProfileConfig(
        base_nav2_params="nav2/params.yaml",
        speed_param_paths=SPEED_PATHS,
        nav2_overrides={"controller_server": {"ros__parameters": {"controller_frequency": 25.0}}},
    )
    overlay = Nav2ParamOverlay(source, profile).patch(speed_mps=0.3, depth_topic="/processed/depth")
    assert overlay.controller_frequency_hz == 25.0
    params = yaml.safe_load(overlay.content)
    assert params["controller_server"]["ros__parameters"] == {
        "FollowPath": {"vx_max": 0.3},
        "controller_frequency": 25.0,
    }
    assert params["velocity_smoother"]["ros__parameters"]["max_velocity"] == [0.3, 0.0, 2.0]
    assert params["local_costmap"]["local_costmap"]["ros__parameters"]["voxel_layer"] == {
        "enabled": True,
        "observation_sources": "scan depth",
        "scan": {"topic": "/scan"},
        "depth": {
            "data_type": "PointCloud2",
            "topic": "/processed/depth",
            "marking": True,
            "clearing": False,
        },
    }
    assert yaml.safe_load(source.read_text(encoding="utf-8")) == BASE_PARAMS


def test_nav2_reads_a_profile_polygon_for_ground_truth(tmp_path: Path) -> None:
    source = tmp_path / "nav2.yaml"
    source.write_text(yaml.safe_dump(BASE_PARAMS), encoding="utf-8")
    vertices = [[0.1, 0.2], [0.1, -0.2], [-0.1, 0.0]]
    profile = GazeboNav2ProfileConfig(
        base_nav2_params="nav2/params.yaml",
        speed_param_paths=SPEED_PATHS,
        nav2_overrides={
            "local_costmap": {"local_costmap": {"ros__parameters": {"footprint": str(vertices)}}}
        },
    )
    overlay = Nav2ParamOverlay(source, profile).patch(speed_mps=0.3, depth_topic="/processed/depth")
    assert overlay.footprint == {"vertices_m": vertices}


@pytest.mark.parametrize(
    "path",
    (
        "missing.vx_max",
        "velocity_smoother.ros__parameters.max_velocity[4]",
        "controller_server.ros__parameters.FollowPath.",
    ),
)
def test_nav2_rejects_nonexistent_speed_parameter(tmp_path: Path, path: str) -> None:
    source = tmp_path / "nav2.yaml"
    source.write_text(yaml.safe_dump(BASE_PARAMS), encoding="utf-8")
    profile = GazeboNav2ProfileConfig(
        base_nav2_params="nav2/params.yaml", speed_param_paths=(path,)
    )
    with pytest.raises(ValidationError, match="speed parameter"):
        Nav2ParamOverlay(source, profile).patch(speed_mps=0.3, depth_topic="/processed/depth")


def test_world_patches_lighting_ground_and_pallet(tmp_path: Path) -> None:
    source = tmp_path / "world.sdf"
    source.write_text(BASE_WORLD, encoding="utf-8")
    pallet = PalletPlacement("dropped_pallet", Pose2D(x=1, y=2, yaw=0.5), 0.135)
    world = SdfPatcher(source).patch(
        lighting_scale=0.5, floor_friction=0.35, real_time_factor=0.75, pallets=(pallet,)
    )

    root = ElementTree.fromstring(world.content)  # noqa: S314 - produced by the safe parser
    assert world.name == "warehouse"
    assert root.findtext(".//scene/ambient") == "0.4 0.3 0.2 1"
    assert [light.text for light in root.findall(".//light/diffuse")] == [
        "0.5 0.4 0.3 1",
        "0.5 0.5 0.5 0.8",
    ]
    assert root.findtext(".//collision/surface/friction/ode/mu") == "0.35"
    assert root.findtext(".//collision/surface/friction/ode/mu2") == "0.35"
    assert root.findtext(".//physics/real_time_factor") == "0.75"
    assert root.findtext(".//include/uri") == "model://dropped_pallet"
    assert root.findtext(".//include/name") == "dropped_pallet_0"
    assert root.findtext(".//include/pose") == "1 2 0.0675 0 0 0.5"
    assert source.read_text(encoding="utf-8") == BASE_WORLD


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ("<!DOCTYPE sdf>\n" + BASE_WORLD, "DOCTYPE"),
        ("<sdf><world>", "invalid SDF"),
        ("<sdf/>", "exactly one named world"),
        (BASE_WORLD.replace("ground_plane", "another_model"), "ground plane"),
        (BASE_WORLD.replace("1 0.8 0.6 1", "invalid"), "RGBA"),
    ],
)
def test_world_rejects_invalid_input(tmp_path: Path, document: str, message: str) -> None:
    source = tmp_path / "world.sdf"
    source.write_text(document, encoding="utf-8")
    with pytest.raises(ValidationError, match=message):
        SdfPatcher(source).patch(
            lighting_scale=0.5, floor_friction=0.5, real_time_factor=1, pallets=()
        )
