"""ROS ``map_server`` YAML/PGM load and write plus occupancy grid alignment (docs/10 §7.1, T-092).

Implements: FR-SIM-003, FR-SCN-002, T-092.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import yaml

from roboprobe.core import errors
from roboprobe.geometry import OccupancyGrid
from roboprobe.geometry.ros_map import decode_ros_pgm

__all__ = [
    "OccupancyIoU",
    "align_occupancy",
    "load_ros_map",
    "occupancy_iou",
    "write_ros_map",
]

_MAX_PIXEL = 255
_ORIGIN_LEN = 3


@dataclass(frozen=True, slots=True)
class OccupancyIoU:
    """Intersection-over-union of occupied cells on a shared sampling grid."""

    iou: float
    agreement: float
    samples: int


def load_ros_map(yaml_path: Path) -> OccupancyGrid:
    """Load a ROS map YAML and its referenced PGM image."""
    try:
        text = yaml_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        msg = f"map YAML not found: {yaml_path}"
        raise errors.NotFoundError(msg, context={"path": str(yaml_path)}) from exc
    meta = yaml.safe_load(text)
    if not isinstance(meta, dict):
        msg = f"{yaml_path}: map metadata must be a mapping"
        raise errors.ValidationError(msg, context={"path": str(yaml_path)})
    image_name = meta.get("image")
    if not isinstance(image_name, str) or not image_name:
        msg = f"{yaml_path}: missing image"
        raise errors.ValidationError(msg, context={"path": str(yaml_path)})
    image_path = (yaml_path.parent / image_name).resolve()
    if not image_path.is_relative_to(yaml_path.parent.resolve()):
        msg = f"{yaml_path}: image must stay inside the map directory"
        raise errors.ValidationError(msg)
    resolution = float(meta["resolution"])
    origin = meta["origin"]
    if not isinstance(origin, list) or len(origin) != _ORIGIN_LEN or origin[2] != 0:
        msg = f"{yaml_path}: origin must be [x, y, 0]"
        raise errors.ValidationError(msg, context={"path": str(yaml_path)})
    try:
        return decode_ros_pgm(
            image_path.read_bytes(),
            resolution=resolution,
            origin=(float(origin[0]), float(origin[1])),
            free_thresh=float(meta["free_thresh"]),
            negate=bool(int(meta.get("negate", 0))),
        )
    except ValueError as exc:
        raise errors.ValidationError(str(exc), context={"path": str(image_path)}) from exc


def write_ros_map(  # noqa: PLR0913
    yaml_path: Path,
    grid: OccupancyGrid,
    *,
    image_name: str | None = None,
    mode: str = "trinary",
    free_thresh: float = 0.1,
    occupied_thresh: float = 0.65,
) -> None:
    """Write ROS map metadata and a binary PGM next to ``yaml_path``."""
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    pgm_name = image_name or f"{yaml_path.stem}.pgm"
    pgm_path = yaml_path.parent / pgm_name
    rows, cols = grid.shape
    pixels = np.flipud(np.where(grid.occupied, 0, _MAX_PIXEL)).astype(np.uint8)
    header = f"P5\n# RoboProbe map export (T-092)\n{cols} {rows}\n255\n".encode()
    pgm_path.write_bytes(header + pixels.tobytes())
    document = {
        "image": pgm_name,
        "mode": mode,
        "resolution": float(grid.resolution),
        "origin": [float(grid.origin[0]), float(grid.origin[1]), 0.0],
        "negate": 0,
        "occupied_thresh": occupied_thresh,
        "free_thresh": free_thresh,
        "height": rows,
        "width": cols,
    }
    yaml_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def align_occupancy(  # noqa: PLR0913
    source: OccupancyGrid,
    *,
    resolution: float,
    origin: tuple[float, float],
    rows: int,
    cols: int,
    outside_occupied: bool = True,
) -> npt.NDArray[np.bool_]:
    """Rasterise ``source`` onto a target lattice."""
    xs = origin[0] + (np.arange(cols) + 0.5) * resolution
    ys = origin[1] + (np.arange(rows) + 0.5) * resolution
    xx, yy = np.meshgrid(xs, ys)
    points = np.column_stack([xx.ravel(), yy.ravel()])
    cells = source.world_to_cell(points).reshape(rows, cols, 2)
    inside = (
        (cells[..., 0] >= 0)
        & (cells[..., 0] < source.shape[0])
        & (cells[..., 1] >= 0)
        & (cells[..., 1] < source.shape[1])
    )
    row = np.clip(cells[..., 0], 0, source.shape[0] - 1)
    col = np.clip(cells[..., 1], 0, source.shape[1] - 1)
    occupied = source.occupied[row, col] & inside
    if outside_occupied:
        occupied = occupied | ~inside
    return occupied


def occupancy_iou(left: OccupancyGrid, right: OccupancyGrid) -> OccupancyIoU:
    """IoU after aligning both grids on the finer resolution lattice."""
    resolution = min(left.resolution, right.resolution)
    x0 = min(left.origin[0], right.origin[0])
    y0 = min(left.origin[1], right.origin[1])
    left_x1 = left.origin[0] + left.shape[1] * left.resolution
    right_x1 = right.origin[0] + right.shape[1] * right.resolution
    left_y1 = left.origin[1] + left.shape[0] * left.resolution
    right_y1 = right.origin[1] + right.shape[0] * right.resolution
    x1 = max(left_x1, right_x1)
    y1 = max(left_y1, right_y1)
    cols = max(1, int(np.ceil((x1 - x0) / resolution)))
    rows = max(1, int(np.ceil((y1 - y0) / resolution)))
    origin = (x0, y0)
    left_mask = align_occupancy(left, resolution=resolution, origin=origin, rows=rows, cols=cols)
    right_mask = align_occupancy(right, resolution=resolution, origin=origin, rows=rows, cols=cols)
    inter = int(np.logical_and(left_mask, right_mask).sum())
    union = int(np.logical_or(left_mask, right_mask).sum())
    samples = left_mask.size
    iou = inter / union if union else 1.0
    agreement = float(np.mean(left_mask == right_mask))
    return OccupancyIoU(iou=iou, agreement=agreement, samples=samples)
