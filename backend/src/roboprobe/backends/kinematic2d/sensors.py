"""Lidar (grid only) and depth camera (grid + pallet) for kinematic2d (docs/10 §7.1).

Implements: FR-SIM-001
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from roboprobe.backends.kinematic2d.model import Kinematic2DModel
from roboprobe.core.settings.backends import Kinematic2DSettings
from roboprobe.geometry import BeamSpec, GridRayCaster, Rect
from roboprobe.perturbation.lidar import apply_dropout, apply_lidar_noise
from roboprobe.perturbation.perception import PerceptionModel

__all__ = ["DepthCamera", "Lidar", "beam_angles"]

FloatArray = npt.NDArray[np.float64]


def beam_angles(n: int, fov_rad: float, *, wrap: bool) -> FloatArray:
    """``n`` beam headings spanning ``fov_rad``, centred on the robot heading.

    ``wrap=True`` omits the duplicate endpoint (full-circle lidar).
    """
    if n < 1:
        msg = f"beam count must be >= 1, got {n}"
        raise ValueError(msg)
    half = fov_rad / 2.0
    return np.linspace(-half, half, n, endpoint=not wrap, dtype=np.float64)


@dataclass(frozen=True, slots=True)
class Lidar:
    """360° lidar that does not see the sub-scan-plane pallet."""

    caster: GridRayCaster
    beams: BeamSpec

    @classmethod
    def from_config(
        cls, caster: GridRayCaster, model: Kinematic2DModel, settings: Kinematic2DSettings
    ) -> Lidar:
        """Build from model file + ``backends.kinematic2d.lidar_beams``."""
        lidar = model.lidar
        angles = beam_angles(settings.lidar_beams, lidar.fov_rad, wrap=True)
        return cls(caster, BeamSpec(angles, lidar.r_min_m, lidar.r_max_m))

    def scan(
        self,
        pose: npt.ArrayLike,
        rng: np.random.Generator,
        noise_std: float,
        dropout: float,
        pallet: Rect | None,
    ) -> FloatArray:
        """Ranges with P4 noise and P8 dropout; pallet is excluded from the geometry."""
        rects = [pallet] if pallet is not None else None
        true = self.caster.cast(pose, self.beams, rects, include_rects=False)
        noisy = apply_lidar_noise(true, noise_std, rng, self.beams.r_min, self.beams.r_max)
        return apply_dropout(noisy, dropout, rng)


@dataclass(frozen=True, slots=True)
class DepthCamera:
    """Forward depth fan that sees walls and the pallet, then illumination degradation."""

    caster: GridRayCaster
    beams: BeamSpec
    perception: PerceptionModel

    @classmethod
    def from_config(
        cls,
        caster: GridRayCaster,
        model: Kinematic2DModel,
        settings: Kinematic2DSettings,
        perception: PerceptionModel,
    ) -> DepthCamera:
        """Build from model file + ``backends.kinematic2d.depth_beams``."""
        depth = model.depth
        r_max = perception.r_max_bright_m
        angles = beam_angles(settings.depth_beams, depth.fov_rad, wrap=False)
        return cls(caster, BeamSpec(angles, depth.r_min_m, r_max), perception)

    def scan(
        self,
        pose: npt.ArrayLike,
        pallet: Rect | None,
        illuminance: float,
        rng: np.random.Generator,
    ) -> FloatArray:
        """True ranges (pallet included) then :meth:`PerceptionModel.degrade`."""
        rects = [pallet] if pallet is not None else None
        true = self.caster.cast(pose, self.beams, rects, include_rects=True)
        return self.perception.degrade(true, illuminance, rng)
