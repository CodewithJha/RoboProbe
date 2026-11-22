"""Rolling local costmap from lidar and depth hits (docs/10 §7.1).

Implements: FR-SIM-001
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt
from scipy import ndimage

from roboprobe.backends.kinematic2d.model import Kinematic2DModel
from roboprobe.geometry import OccupancyGrid

__all__ = ["RollingCostmap", "inflate", "overlay_sensor_hits", "sensor_hit_occupancy"]

FloatArray = npt.NDArray[np.float64]


def inflate(occupied: npt.NDArray[np.bool_], radius_cells: int) -> npt.NDArray[np.bool_]:
    """Binary dilation by ``radius_cells`` (4-connected square)."""
    if radius_cells <= 0:
        return occupied.copy()
    window = 2 * radius_cells + 1
    return np.asarray(
        ndimage.maximum_filter(occupied, size=window, mode="constant", cval=0), dtype=np.bool_
    )


def overlay_sensor_hits(  # noqa: PLR0913,PLR0917
    grid: OccupancyGrid,
    pose: tuple[float, float, float],
    lidar_ranges: FloatArray,
    lidar_angles: FloatArray,
    depth_ranges: FloatArray,
    depth_angles: FloatArray,
    *,
    lidar_inflation_cells: int = 1,
    depth_inflation_cells: int = 0,
) -> OccupancyGrid:
    """Return a copy of ``grid`` with finite sensor endpoints marked occupied (optional inflate)."""
    occupied = sensor_hit_occupancy(
        grid,
        grid.occupied,
        pose,
        lidar_ranges,
        lidar_angles,
        depth_ranges,
        depth_angles,
        lidar_inflation_cells=lidar_inflation_cells,
        depth_inflation_cells=depth_inflation_cells,
    )
    return OccupancyGrid(occupied, grid.resolution, grid.origin)


def sensor_hit_occupancy(  # noqa: PLR0913,PLR0917 - two sensors and their inflation radii
    grid: OccupancyGrid,
    static_occupied: npt.NDArray[np.bool_],
    pose: tuple[float, float, float],
    lidar_ranges: FloatArray,
    lidar_angles: FloatArray,
    depth_ranges: FloatArray,
    depth_angles: FloatArray,
    *,
    lidar_inflation_cells: int,
    depth_inflation_cells: int,
) -> npt.NDArray[np.bool_]:
    """Compose the planning mask without computing a distance transform."""
    occupied = static_occupied.copy()
    specs = (
        (lidar_ranges, lidar_angles, lidar_inflation_cells),
        (depth_ranges, depth_angles, depth_inflation_cells),
    )
    for sensor in specs:
        _mark_world_cells(occupied, grid, pose, sensor)
    return occupied


def _mark_world_cells(
    occupied: npt.NDArray[np.bool_],
    grid: OccupancyGrid,
    pose: tuple[float, float, float],
    sensor: tuple[FloatArray, FloatArray, int],
) -> None:
    ranges, angles, inflate_cells = sensor
    radius = max(0, inflate_cells)
    finite = np.isfinite(ranges)
    if not np.any(finite):
        return
    heading = pose[2] + angles[finite]
    x = pose[0] + ranges[finite] * np.cos(heading)
    y = pose[1] + ranges[finite] * np.sin(heading)
    cells = grid.world_to_cell(np.stack([x, y], axis=1))
    rows, cols = grid.shape
    for row, col in cells:
        if 0 <= row < rows and 0 <= col < cols:
            occupied[
                max(0, row - radius) : min(rows, row + radius + 1),
                max(0, col - radius) : min(cols, col + radius + 1),
            ] = True


class RollingCostmap:
    """Local occupancy around the robot, marked from sensor hits and cleared along rays."""

    def __init__(self, model: Kinematic2DModel) -> None:
        """Allocate the rolling grid from costmap model constants."""
        cfg = model.costmap
        n = max(1, round(cfg.size_m / cfg.resolution_m))
        self.resolution = cfg.resolution_m
        self.inflation_m = cfg.inflation_m
        self._n = n
        self._occupied = np.zeros((n, n), dtype=np.bool_)
        self._origin = (0.0, 0.0)

    def update(  # noqa: PLR0913,PLR0917
        self,
        pose: tuple[float, float, float],
        lidar_hits: FloatArray,
        lidar_angles: FloatArray,
        depth_hits: FloatArray,
        depth_angles: FloatArray,
        world: OccupancyGrid | None = None,
    ) -> None:
        """Recentre on ``pose``, copy static world cells, then mark finite sensor hits."""
        half = self._n * self.resolution / 2.0
        self._origin = (pose[0] - half, pose[1] - half)
        self._occupied.fill(False)
        if world is not None:
            self._stamp_world(world)
        self._mark_hits(pose, lidar_hits, lidar_angles)
        self._mark_hits(pose, depth_hits, depth_angles)

    def _stamp_world(self, world: OccupancyGrid) -> None:
        n = self._n
        xs = self._origin[0] + (np.arange(n) + 0.5) * self.resolution
        ys = self._origin[1] + (np.arange(n) + 0.5) * self.resolution
        xx, yy = np.meshgrid(xs, ys)
        points = np.stack([xx.ravel(), yy.ravel()], axis=1)
        cells = world.world_to_cell(points)
        rows, cols = world.shape
        r, c = cells[:, 0], cells[:, 1]
        inside = (r >= 0) & (r < rows) & (c >= 0) & (c < cols)
        occ = np.zeros(n * n, dtype=np.bool_)
        occ[inside] = world.occupied[r[inside], c[inside]]
        self._occupied |= occ.reshape(n, n)

    def inflated(self) -> OccupancyGrid:
        """Inflated local grid for the planner."""
        radius = math.ceil(self.inflation_m / self.resolution)
        return OccupancyGrid(inflate(self._occupied, radius), self.resolution, self._origin)

    def _mark_hits(
        self, pose: tuple[float, float, float], ranges: FloatArray, angles: FloatArray
    ) -> None:
        finite = np.isfinite(ranges)
        heading = pose[2] + angles[finite]
        x = pose[0] + ranges[finite] * np.cos(heading)
        y = pose[1] + ranges[finite] * np.sin(heading)
        col = np.floor((x - self._origin[0]) / self.resolution).astype(np.int64)
        row = np.floor((y - self._origin[1]) / self.resolution).astype(np.int64)
        inside = (row >= 0) & (row < self._n) & (col >= 0) & (col < self._n)
        self._occupied[row[inside], col[inside]] = True
