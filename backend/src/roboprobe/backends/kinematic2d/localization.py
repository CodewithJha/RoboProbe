"""Odometry dead-reckoning plus scan-matching correction (docs/10 §7.1).

Scan matching is approximated as a correlative pull toward ground truth, weighted by
``k = clip(k0 * (1 - P4 / lidar_noise_ref) * (1 - P8), 0, 1)``. The ``localization`` RNG
stream is consumed so the approximation stays deterministic.

Implements: FR-SIM-001
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from roboprobe.backends.kinematic2d.model import Kinematic2DModel

__all__ = ["Localizer", "scan_match_gain"]


def scan_match_gain(model: Kinematic2DModel, lidar_noise_std: float, dropout: float) -> float:
    """Localisation correction gain in ``[0, 1]``."""
    loc = model.localization
    raw = loc.k0 * (1.0 - lidar_noise_std / loc.lidar_noise_ref_m) * (1.0 - dropout)
    return float(min(1.0, max(0.0, raw)))


@dataclass(slots=True)
class Localizer:
    """Estimated pose; ``update`` blends odometry with a GT-directed scan match."""

    x: float
    y: float
    yaw: float
    gain: float

    def update(
        self,
        odom_delta: tuple[float, float, float],
        gt: tuple[float, float, float],
        rng: np.random.Generator,
    ) -> tuple[float, float, float]:
        """Apply odometry delta then pull toward ``gt`` with :attr:`gain`.

        ``rng`` is drawn once per call so later consumers of the stream stay aligned.
        """
        dx, dy, dyaw = odom_delta
        _ = float(rng.random())
        pred_x = self.x + dx
        pred_y = self.y + dy
        pred_yaw = self.yaw + dyaw
        k = self.gain
        self.x = pred_x + k * (gt[0] - pred_x)
        self.y = pred_y + k * (gt[1] - pred_y)
        self.yaw = pred_yaw + k * (gt[2] - pred_yaw)
        return self.x, self.y, self.yaw
