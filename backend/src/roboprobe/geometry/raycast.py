"""Vectorised 2-D ray casting against an occupancy grid and analytic rectangles (docs/10 §7.1).

Used by the kinematic2d lidar (180 beams, does **not** see the sub-scan-plane pallet, so
``include_rects=False``) and depth camera (60 beams, sees pallet and walls).

Grid algorithm: fixed-step marching at half a cell, vectorised over beams and steps in chunks
(beams that hit drop out between chunks), with float32 cell coordinates and a single gather into
a free-padded copy of the grid. The range is then refined to the exact entry point of the hit
cell's square (slab test), so axis-aligned walls are exact and the worst case (a corner cell
skipped by the half-cell step) is within one cell. Fixed-step marching was preferred to an
Amanatides-Woo DDA, which needs a Python loop over traversed cells; marching is a few NumPy
operations (see ``tests/benchmark/test_raycast_bench.py``).

Rectangles are intersected analytically (slab test in the rectangle frame). Beams that leave the
grid without a hit see free space. Ranges are clipped to ``[r_min, r_max]``: no hit gives
``r_max`` and a hit closer than ``r_min`` gives ``r_min``.

Frames and units: ``pose = (x, y, yaw)`` of the sensor in the world [m, rad]; beam angles are
relative to ``yaw`` [rad]; ranges in metres.

Layer: Kernel (L1); NumPy only (vendorable).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

import numpy as np
import numpy.typing as npt

from roboprobe.geometry._arrays import POSE_DIM, FloatArray, rotation
from roboprobe.geometry.distance import Rect
from roboprobe.geometry.grid import OccupancyGrid

__all__ = ["BeamSpec", "GridRayCaster", "cast"]

IntArray = npt.NDArray[np.intp]

_STEPS_PER_CELL: Final = 2
"""Marching samples per cell length; half-cell steps bound the corner-skipping error by a cell."""
_CHUNK_STEPS: Final = 128
"""Samples marched per vectorised chunk; beams that already hit drop out between chunks."""


@dataclass(frozen=True, slots=True, eq=False)
class BeamSpec:
    """A sensor's beam fan: ``angles`` relative to its heading [rad] and range limits [m].

    Built (and validated) once per sensor from backend configuration, then reused every step.
    """

    angles: FloatArray = field(repr=False)
    r_min: float
    r_max: float

    def __post_init__(self) -> None:
        """Validate and freeze the fan."""
        angles = np.array(self.angles, dtype=np.float64)
        if angles.ndim != 1 or angles.size == 0 or not np.all(np.isfinite(angles)):
            msg = f"angles must be a finite non-empty 1-D array, got shape {angles.shape}"
            raise ValueError(msg)
        if not (np.isfinite(self.r_min) and np.isfinite(self.r_max)):
            msg = f"range limits must be finite, got {self.r_min}, {self.r_max}"
            raise ValueError(msg)
        if not 0.0 <= self.r_min < self.r_max:
            msg = f"range limits must satisfy 0 <= r_min < r_max, got {self.r_min}, {self.r_max}"
            raise ValueError(msg)
        angles.setflags(write=False)
        object.__setattr__(self, "angles", angles)


class GridRayCaster:
    """Ray caster bound to one grid; build it once per world and call :meth:`cast` every step.

    Construction pads the grid with a free border so marching needs a single clipped gather.
    """

    __slots__ = ("_cols", "_flat", "_grid", "_origin_cells")

    def __init__(self, grid: OccupancyGrid) -> None:
        """Precompute the padded, flattened occupancy for ``grid``."""
        padded = np.zeros((grid.shape[0] + 2, grid.shape[1] + 2), dtype=np.bool_)
        padded[1:-1, 1:-1] = grid.occupied
        self._grid = grid
        self._flat = padded.ravel()
        self._cols = padded.shape[1]
        # +1 converts grid cells to padded cells.
        self._origin_cells = np.asarray(grid.origin, dtype=np.float64) / grid.resolution - 1.0

    @property
    def grid(self) -> OccupancyGrid:
        """The grid this caster was built for."""
        return self._grid

    def cast(
        self,
        pose: npt.ArrayLike,
        beams: BeamSpec,
        rects: Sequence[Rect] | None = None,
        *,
        include_rects: bool = True,
    ) -> FloatArray:
        """Cast ``beams`` from ``pose``; ranges ``(n_beams,)`` clipped to ``[r_min, r_max]``.

        Args:
            pose: Sensor pose ``(x, y, yaw)``.
            beams: Beam angles and range limits.
            rects: Analytic obstacles (e.g. the injected pallet).
            include_rects: ``False`` ignores ``rects`` (sensor plane above the obstacle).

        Raises:
            ValueError: For a malformed pose.
        """
        p = np.asarray(pose, dtype=np.float64)
        if p.shape != (POSE_DIM,) or not np.all(np.isfinite(p)):
            msg = f"pose must be a finite (x, y, yaw), got shape {p.shape}"
            raise ValueError(msg)
        origin = p[:2]
        heading = p[2] + beams.angles
        directions = np.stack([np.cos(heading), np.sin(heading)], axis=-1)
        hits = self._cast_grid(origin, directions, beams.r_max)
        if include_rects and rects:
            for rect in rects:
                hits = np.minimum(hits, _cast_rect(rect, origin, directions))
        return np.clip(hits, beams.r_min, beams.r_max)

    def _first_hits(
        self, origin: FloatArray, directions: FloatArray, n_steps: int
    ) -> tuple[IntArray, IntArray]:
        """First occupied marching sample per beam (``-1`` if none) and its grid ``(row, col)``."""
        rows_max, cols_max = self._grid.shape[0] + 1, self._grid.shape[1] + 1
        start = (origin / self._grid.resolution - self._origin_cells).astype(np.float32)
        dirs = directions.astype(np.float32)
        first = np.full(len(directions), -1, dtype=np.intp)
        cells = np.zeros((len(directions), 2), dtype=np.intp)
        active = np.arange(len(directions))
        for begin in range(0, n_steps, _CHUNK_STEPS):
            stop = min(begin + _CHUNK_STEPS, n_steps)
            along = (np.arange(begin, stop) / _STEPS_PER_CELL).astype(np.float32)
            cols = np.clip(start[0] + np.outer(dirs[active, 0], along), 0, cols_max).astype(np.intp)
            rows = np.clip(start[1] + np.outer(dirs[active, 1], along), 0, rows_max).astype(np.intp)
            occupied = self._flat[rows * self._cols + cols]
            hit = occupied.any(axis=1)
            index = occupied[hit].argmax(axis=1)
            beams_hit = active[hit]
            first[beams_hit] = begin + index
            # The hit cell comes from the very samples that hit (padded -> grid indices), so the
            # refinement below never re-derives it with different rounding.
            cells[beams_hit, 0] = rows[hit, index] - 1
            cells[beams_hit, 1] = cols[hit, index] - 1
            active = active[~hit]
            if active.size == 0:
                break
        return first, cells

    def _cast_grid(self, origin: FloatArray, directions: FloatArray, r_max: float) -> FloatArray:
        """Distance to the first occupied cell per beam (``inf`` if none within ``r_max``)."""
        resolution = self._grid.resolution
        step = resolution / _STEPS_PER_CELL
        n_steps = int(np.ceil(r_max / step)) + 1
        first, cells = self._first_hits(origin, directions, n_steps)
        result = np.full(len(directions), np.inf)
        beam = np.flatnonzero(first >= 0)
        if beam.size == 0:
            return result
        t_hit = first[beam] * step
        lower = np.asarray(self._grid.origin) + cells[beam, ::-1] * resolution
        entry = _slab_entry(origin, directions[beam], lower, lower + resolution)
        # The true entry lies within the last marching step; if rounding put the sample in a cell
        # the exact ray only grazes (slab miss -> inf), the sample distance itself is used.
        result[beam] = np.clip(entry, np.maximum(t_hit - step, 0.0), t_hit)
        return result


def cast(
    grid: OccupancyGrid,
    pose: npt.ArrayLike,
    beams: BeamSpec,
    rects: Sequence[Rect] | None = None,
    *,
    include_rects: bool = True,
) -> FloatArray:
    """One-off :meth:`GridRayCaster.cast`; per-step callers should keep a :class:`GridRayCaster`."""
    return GridRayCaster(grid).cast(pose, beams, rects, include_rects=include_rects)


def _cast_rect(rect: Rect, origin: FloatArray, directions: FloatArray) -> FloatArray:
    """Analytic distance to a rectangle per beam (``inf`` if missed, ``0`` from inside)."""
    local_origin = rect.to_local(origin)
    local_dirs = directions @ rotation(np.array([rect.yaw]))[0]
    half = np.array([rect.length, rect.width]) / 2
    return _slab_entry(local_origin, local_dirs, -half, half)


def _slab_entry(
    origin: FloatArray, directions: FloatArray, lower: FloatArray, upper: FloatArray
) -> FloatArray:
    """Ray/axis-aligned-box entry distance (``0`` from inside, ``inf`` on a miss)."""
    # Tiny or zero direction components overflow to +-inf, which the slab test handles.
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        inverse = 1.0 / directions
        t1 = (lower - origin) * inverse
        t2 = (upper - origin) * inverse
    # A zero direction component gives +-inf (or nan when the origin is on the slab plane).
    near = np.nan_to_num(np.minimum(t1, t2), nan=-np.inf)
    far = np.nan_to_num(np.maximum(t1, t2), nan=np.inf)
    t_enter = np.maximum(near.max(axis=-1), 0.0)
    t_exit = far.min(axis=-1)
    return np.where(t_enter <= t_exit, t_enter, np.inf)
