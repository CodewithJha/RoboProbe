"""Simulator backend settings (docs/27 §4.5).

Layer: Kernel (L1).
"""

from pathlib import Path
from typing import Literal

from pydantic import Field

from roboprobe.core.settings._base import SettingsSection

__all__ = [
    "BackendsSettings",
    "GazeboNav2Settings",
    "GazeboPhysicsSettings",
    "Kinematic2DSettings",
]

ROS_DOMAIN_ID_MAX = 232
"""Largest ROS 2 domain id accepted by DDS port mapping."""

RecordBagPolicy = Literal["never", "failures", "always"]


class Kinematic2DSettings(SettingsSection):
    """In-process 2-D kinematic backend (ADR-0003)."""

    dt: float = Field(default=0.05, gt=0, description="Integration time step [s].")
    sample_hz: float = Field(default=20.0, gt=0, description="Trace sampling rate [Hz].")
    lidar_beams: int = Field(default=180, gt=0, description="Simulated lidar beams.")
    depth_beams: int = Field(default=60, gt=0, description="Simulated depth-camera beams.")
    model_file: Path = Field(
        default=Path("configs/backends/kinematic2d_v1.yaml"),
        description="Robot, controller and planner constants (calibrated in T-034) [path].",
    )
    perception_model_file: Path = Field(
        default=Path("configs/perception/oakd_k2d_v1.yaml"),
        description="Perception degradation constants for depth simulation (T-034) [path].",
    )
    calibration_file: Path = Field(
        default=Path("configs/reference/k2d_gt_canonical.yaml"),
        description="Designed GT canonical unit-cube points (T-034) [path].",
    )


class GazeboPhysicsSettings(SettingsSection):
    """Gazebo physics engine settings."""

    real_time_factor: float = Field(
        default=1.0, gt=0, description="Target real-time factor of the simulation."
    )


class GazeboNav2Settings(SettingsSection):
    """Gazebo Harmonic + Nav2 backend (ADR-0002)."""

    image: str = Field(
        default="ghcr.io/codewithjha/roboprobe-gazebo:${tag}",
        description="Worker image reference recorded in run manifests (informational).",
    )
    launch_package: str = Field(default="roboprobe_ros", description="ROS package of the launch.")
    launch_file: str = Field(default="episode.launch.py", description="Episode launch file.")
    topics_file: Path = Field(
        default=Path("ros_ws/src/roboprobe_ros/config/topics.yaml"),
        description="Topic and frame names used by the ROS nodes [path].",
    )
    base_world: str = Field(
        default="nav2_minimal_tb4_sim/worlds/warehouse.sdf",
        description="Package-relative base world patched per scenario.",
    )
    base_nav2_params: str = Field(
        default="nav2_bringup/params/nav2_params.yaml",
        description="Package-relative Nav2 parameter file overlaid per SUT profile.",
    )
    headless_rendering: bool = Field(default=True, description="Run Gazebo without a GUI.")
    software_rendering: bool = Field(
        default=False, description="Force Mesa software rendering (`LIBGL_ALWAYS_SOFTWARE=1`)."
    )
    physics: GazeboPhysicsSettings = Field(default_factory=GazeboPhysicsSettings)
    rmw: str = Field(default="rmw_cyclonedds_cpp", description="ROS 2 middleware implementation.")
    domain_id_base: int = Field(
        default=30,
        ge=0,
        le=ROS_DOMAIN_ID_MAX,
        description="First `ROS_DOMAIN_ID`; each worker slot adds its index.",
    )
    startup_timeout_s: float = Field(
        default=60.0, gt=0, description="Time allowed for Nav2 to become ACTIVE [s]."
    )
    wall_margin_s: float = Field(
        default=30.0,
        ge=0,
        description="Extra wall time after estimated startup and navigation [s].",
    )
    teardown_grace_s: float = Field(
        default=10.0, gt=0, description="Time from SIGINT to SIGTERM on episode teardown [s]."
    )
    teardown_term_wait_s: float = Field(
        default=5.0, ge=0, description="Time from SIGTERM to SIGKILL after an episode [s]."
    )
    sample_hz: float = Field(default=20.0, gt=0, description="Trace sampling rate [Hz].")
    record_bag: RecordBagPolicy = Field(
        default="failures",
        description=(
            "MCAP recording policy. Choose never, always, or failures (confirmations, "
            "manual runs and replays of a FAIL run)."
        ),
    )
    max_parallel_per_host: int = Field(
        default=1, gt=0, description="Gazebo episodes allowed in parallel on one host."
    )
    perception_model_file: Path = Field(
        default=Path("configs/perception/oakd_lowlight_v1.yaml"),
        description="Perception degradation constants (docs/06 §3.3) [path].",
    )


class BackendsSettings(SettingsSection):
    """Settings of every simulator backend."""

    kinematic2d: Kinematic2DSettings = Field(default_factory=Kinematic2DSettings)
    gazebo_nav2: GazeboNav2Settings = Field(default_factory=GazeboNav2Settings)
