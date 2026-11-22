"""Typed kinematic2d model file (docs/10 §7.1).

Implements: FR-SIM-001, NFR-CFG-001
"""

from __future__ import annotations

from pathlib import Path
from typing import Self

import pydantic
import yaml
from pydantic import BaseModel, ConfigDict, Field

from roboprobe.core import errors

__all__ = ["Kinematic2DModel"]

_SCHEMA_VERSION = 1


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RobotModel(_Section):
    """Unicycle body and acceleration limits."""

    footprint_radius_m: float = Field(gt=0)
    a_max_mps2: float = Field(gt=0)
    alpha_max_radps2: float = Field(gt=0)


class LidarModel(_Section):
    """2-D lidar fan (beam count comes from settings)."""

    r_min_m: float = Field(ge=0)
    r_max_m: float = Field(gt=0)
    fov_rad: float = Field(gt=0)


class DepthModel(_Section):
    """Depth-camera fan (beam count comes from settings)."""

    r_min_m: float = Field(ge=0)
    fov_rad: float = Field(gt=0)


class LocalizationModel(_Section):
    """Scan-matching gain ``k = k0 * (1 - P4 / lidar_noise_ref_m) * (1 - P8)``."""

    k0: float = Field(gt=0, le=1)
    lidar_noise_ref_m: float = Field(gt=0)


class CostmapModel(_Section):
    """Rolling local occupancy used by the planner."""

    inflation_m: float = Field(ge=0)
    size_m: float = Field(gt=0)
    resolution_m: float = Field(gt=0)
    lidar_hit_inflation_cells: int = Field(default=1, ge=0)
    depth_hit_inflation_cells: int = Field(default=0, ge=0)
    lidar_overlay_min_noise_std_m: float = Field(
        default=0.04,
        ge=0.0,
        description="P4 below this skips marking phantom lidar obstacles on the global plan.",
    )


class PlannerModel(_Section):
    """Global A* replanning rate."""

    replan_hz: float = Field(gt=0)


class ControllerModel(_Section):
    """Regulated pure-pursuit constants (docs/10 §7.1)."""

    lookahead_m: float = Field(gt=0)
    proximity_m: float = Field(gt=0)
    curvature_gain_m: float = Field(ge=0)


class FrictionModel(_Section):
    """Traction model constants (docs/06 §3.5); calibrated with the rest of the model (T-034)."""

    mu_base: float = Field(default=0.15, gt=0)
    yaw_slip_exponent: float = Field(default=1.5, gt=0)


class WorldModel(_Section):
    """Warehouse occupancy clone dimensions (docs/06 §1 start pose)."""

    resolution_m: float = Field(gt=0)
    origin_x_m: float
    origin_y_m: float
    width_m: float = Field(gt=0)
    height_m: float = Field(gt=0)
    wall_thickness_m: float = Field(gt=0)
    aisle_x_m: float
    aisle_half_width_m: float = Field(gt=0)
    shelf_y0_m: float
    shelf_y1_m: float
    start_x_m: float
    start_y_m: float
    goal_x_m: float
    goal_y_m: float


class Kinematic2DModel(_Section):
    """All kinematic2d physical constants from ``backends.kinematic2d.model_file``."""

    schema_version: int
    id: str = Field(min_length=1)
    robot: RobotModel
    lidar: LidarModel
    depth: DepthModel
    localization: LocalizationModel
    costmap: CostmapModel
    planner: PlannerModel
    controller: ControllerModel
    friction: FrictionModel = Field(default_factory=FrictionModel)
    world: WorldModel

    @classmethod
    def from_yaml(cls, path: Path) -> Self:
        """Load and validate a model file.

        Raises:
            roboprobe.core.errors.NotFoundError: If ``path`` does not exist.
            roboprobe.core.errors.ValidationError: On YAML or schema errors.
        """
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            msg = f"kinematic2d model not found: {path}"
            raise errors.NotFoundError(msg, context={"path": str(path)}) from exc
        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            msg = f"{path}: invalid YAML: {exc}"
            raise errors.ValidationError(msg, context={"path": str(path)}) from exc
        if not isinstance(document, dict) or document.get("schema_version") != _SCHEMA_VERSION:
            msg = f"{path}: expected mapping with schema_version {_SCHEMA_VERSION}"
            raise errors.ValidationError(msg, context={"path": str(path)})
        try:
            return cls.model_validate(document)
        except (TypeError, pydantic.ValidationError) as exc:
            msg = f"{path}: invalid kinematic2d model: {exc}"
            raise errors.ValidationError(
                msg, context={"path": str(path), "reason": str(exc)}
            ) from exc
