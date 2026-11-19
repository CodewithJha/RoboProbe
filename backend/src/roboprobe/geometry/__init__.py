"""Footprint geometry, occupancy grids and distance transforms (shared with the ROS package).

Pure NumPy/SciPy with no other roboprobe imports, so ``ground_truth_monitor`` can vendor it and
both backends compute ``min_obstacle_dist`` with the same algorithm (docs/10 §6). Units are metres
and radians; invalid inputs raise :class:`ValueError` (callers translate at their boundary).

Layer: Kernel (L1). See docs/16 §2 for the allowed import directions.
"""

from roboprobe.geometry.distance import (
    Rect,
    footprint_grid_distance,
    footprint_rect_distance,
    min_obstacle_distance,
    point_rect_distance,
    point_segment_distance,
    polygon_distance,
)
from roboprobe.geometry.footprint import CircleFootprint, Footprint, PolygonFootprint
from roboprobe.geometry.grid import OccupancyGrid

__all__ = [
    "CircleFootprint",
    "Footprint",
    "OccupancyGrid",
    "PolygonFootprint",
    "Rect",
    "footprint_grid_distance",
    "footprint_rect_distance",
    "min_obstacle_distance",
    "point_rect_distance",
    "point_segment_distance",
    "polygon_distance",
]
