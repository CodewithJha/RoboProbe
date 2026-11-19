"""Occupancy grid with world/cell transforms and a metric distance field.

Convention (ROS ``map_server``): ``occupied[row, col]``; ``origin`` is the world position of the
lower-left corner of cell ``(0, 0)``; rows grow along world ``+y`` and columns along ``+x``; every
cell is a ``resolution``-metre square.

The distance field treats occupied cells as filled squares: for a free cell it is the Euclidean
distance between cell centres (``scipy.ndimage.distance_transform_edt``) minus half a cell, so it
approximates the distance to the nearest obstacle *boundary* to within one cell; occupied cells
are ``0``. Points outside the grid get distance ``0``: leaving the known map is never "safe".

Layer: Kernel (L1); NumPy/SciPy only so it can be vendored into the ROS package (docs/10 §6).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt
from scipy import ndimage

from roboprobe.geometry._arrays import POINT_DIM, FloatArray, as_points

__all__ = ["OccupancyGrid"]


@dataclass(frozen=True, slots=True, eq=False)
class OccupancyGrid:
    """Immutable boolean occupancy grid; build once per world and reuse for every pose."""

    occupied: npt.NDArray[np.bool_] = field(repr=False)
    resolution: float
    origin: tuple[float, float] = (0.0, 0.0)
    _distance: FloatArray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate inputs and precompute the distance field."""
        occupied = np.asarray(self.occupied, dtype=np.bool_)
        if occupied.ndim != POINT_DIM or occupied.size == 0:
            msg = f"occupied must be a non-empty 2-D array, got shape {occupied.shape}"
            raise ValueError(msg)
        if not (np.isfinite(self.resolution) and self.resolution > 0):
            msg = f"resolution must be finite and > 0, got {self.resolution}"
            raise ValueError(msg)
        as_points(self.origin, "origin")
        occupied = occupied.copy()
        occupied.setflags(write=False)
        object.__setattr__(self, "occupied", occupied)
        object.__setattr__(self, "_distance", self._distance_field(occupied))

    def _distance_field(self, occupied: npt.NDArray[np.bool_]) -> FloatArray:
        if not occupied.any():
            field_ = np.full(occupied.shape, np.inf)
        else:
            edt = ndimage.distance_transform_edt(~occupied, sampling=self.resolution)
            field_ = np.where(occupied, 0.0, np.maximum(edt - self.resolution / 2, 0.0))
        field_.setflags(write=False)
        return field_

    @property
    def shape(self) -> tuple[int, int]:
        """``(rows, cols)``."""
        rows, cols = self.occupied.shape
        return rows, cols

    @property
    def distance_field(self) -> FloatArray:
        """Read-only per-cell distance to the nearest obstacle [m] (``inf`` for an empty grid)."""
        return self._distance

    def world_to_cell(self, points: npt.ArrayLike) -> npt.NDArray[np.int64]:
        """Integer ``(row, col)`` of the cells containing ``points`` (may lie outside the grid)."""
        xy = (as_points(points) - np.asarray(self.origin)) / self.resolution
        return np.asarray(np.floor(xy[..., ::-1]), dtype=np.int64)

    def cell_to_world(self, cells: npt.ArrayLike) -> FloatArray:
        """World coordinates ``(..., 2)`` of the centres of ``(row, col)`` cells."""
        rc = np.asarray(cells, dtype=np.float64)
        centres = (rc[..., ::-1] + 0.5) * self.resolution + np.asarray(self.origin)
        return np.asarray(centres, dtype=np.float64)

    def contains(self, points: npt.ArrayLike) -> npt.NDArray[np.bool_]:
        """Whether each world point lies inside the grid."""
        cells = self.world_to_cell(points)
        rows, cols = self.shape
        return (
            (cells[..., 0] >= 0)
            & (cells[..., 0] < rows)
            & (cells[..., 1] >= 0)
            & (cells[..., 1] < cols)
        )

    def distance_at(self, points: npt.ArrayLike) -> FloatArray:
        """Distance field sampled at world ``points`` (``...`` shape); ``0`` outside the grid."""
        cells = self.world_to_cell(points)
        inside = self.contains(points)
        rows, cols = self.shape
        r = np.clip(cells[..., 0], 0, rows - 1)
        c = np.clip(cells[..., 1], 0, cols - 1)
        return np.where(inside, self._distance[r, c], 0.0)
