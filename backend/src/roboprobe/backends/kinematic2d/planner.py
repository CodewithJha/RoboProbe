"""A* global planner on an inflated occupancy grid (docs/10 §7.1).

Implements: FR-SIM-001
"""

from __future__ import annotations

import heapq
import math

import numpy as np
import numpy.typing as npt

from roboprobe.geometry import OccupancyGrid

__all__ = ["plan_path"]

_SQRT2 = math.sqrt(2.0)
_NEIGHBOURS: tuple[tuple[int, int, float], ...] = (
    (-1, 0, 1.0),
    (1, 0, 1.0),
    (0, -1, 1.0),
    (0, 1, 1.0),
    (-1, -1, _SQRT2),
    (-1, 1, _SQRT2),
    (1, -1, _SQRT2),
    (1, 1, _SQRT2),
)


def plan_path(
    grid: OccupancyGrid,
    start: tuple[float, float],
    goal: tuple[float, float],
    *,
    occupied: npt.NDArray[np.bool_] | None = None,
) -> npt.NDArray[np.float64] | None:
    """8-connected A* on free cells. ``None`` if start/goal occupied or no path."""
    start_cell = _cell(grid, start)
    goal_cell = _cell(grid, goal)
    if start_cell is None or goal_cell is None:
        return None
    rows, cols = grid.shape
    if occupied is None:
        occupied = grid.occupied
    sr, sc = start_cell
    gr, gc = goal_cell
    if occupied[sr, sc] or occupied[gr, gc]:
        return None
    if start_cell == goal_cell:
        return grid.cell_to_world(np.array([[sr, sc]], dtype=np.int64))

    g_score = {(sr, sc): 0.0}
    came: dict[tuple[int, int], tuple[int, int]] = {}
    open_heap: list[tuple[float, int, int]] = [(float(_heuristic(sr, sc, gr, gc)), sr, sc)]
    closed: set[tuple[int, int]] = set()

    while open_heap:
        _, r, c = heapq.heappop(open_heap)
        if (r, c) in closed:
            continue
        closed.add((r, c))
        if (r, c) == (gr, gc):
            return _reconstruct(grid, came, (r, c), (sr, sc))
        for dr, dc, cost in _NEIGHBOURS:
            nr, nc = r + dr, c + dc
            if (
                nr < 0
                or nr >= rows
                or nc < 0
                or nc >= cols
                or occupied[nr, nc]
                or (nr, nc) in closed
            ):
                continue
            tentative = g_score[r, c] + cost * grid.resolution
            if tentative >= g_score.get((nr, nc), math.inf):
                continue
            came[nr, nc] = (r, c)
            g_score[nr, nc] = tentative
            heapq.heappush(open_heap, (tentative + _heuristic(nr, nc, gr, gc), nr, nc))
    return None


def _heuristic(r: int, c: int, gr: int, gc: int) -> float:
    return math.hypot(r - gr, c - gc)


def _cell(grid: OccupancyGrid, xy: tuple[float, float]) -> tuple[int, int] | None:
    rc = grid.world_to_cell(np.array(xy, dtype=np.float64))
    r, c = int(rc[0]), int(rc[1])
    rows, cols = grid.shape
    if r < 0 or r >= rows or c < 0 or c >= cols:
        return None
    return r, c


def _reconstruct(
    grid: OccupancyGrid,
    came: dict[tuple[int, int], tuple[int, int]],
    current: tuple[int, int],
    start: tuple[int, int],
) -> npt.NDArray[np.float64]:
    cells = [current]
    while current != start:
        current = came[current]
        cells.append(current)
    cells.reverse()
    return grid.cell_to_world(np.asarray(cells, dtype=np.int64))
