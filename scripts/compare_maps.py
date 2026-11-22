"""Compare the Nav2 warehouse occupancy and nominal path with the k2d clone (T-092)."""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, Field

from roboprobe.backends.kinematic2d.world import load_world
from roboprobe.core.settings.oracles import ClearanceThresholds
from roboprobe.geometry import OccupancyGrid
from roboprobe.scenario._documents import load_yaml_document
from roboprobe.scenario.task import load_nominal_path, load_task, polyline_length_m

REPO_ROOT = Path(__file__).resolve().parents[1]
_PGM = re.compile(rb"P5\s+(?:\s|#[^\n]*\n)*(\d+)\s+(\d+)\s+255(?:\r\n|\s)")
_MAX_PIXEL = 255.0
_CELL_TOLERANCE = 1e-7
MIN_IOU = 0.95
MAX_PATH_RELATIVE_ERROR = 0.02
MAX_ORIGIN_OFFSET_CELLS = 1


class _MapDescriptor(BaseModel):
    image: str
    mode: Literal["trinary"]
    resolution: float = Field(gt=0)
    origin: tuple[float, float, Literal[0]]
    negate: Literal[0]
    occupied_thresh: float = Field(gt=0, le=1)
    free_thresh: float = Field(ge=0, lt=1)


@dataclass(frozen=True, slots=True)
class Alignment:
    """Measured overlap, origin offset and relative length difference."""

    occupied_iou: float
    origin_offset_cells: tuple[int, int]
    nav2_path_m: float
    k2d_path_m: float
    path_relative_error: float
    min_clearance_m: float

    def passes(self) -> bool:
        """Check the T-092 alignment thresholds."""
        return (
            self.occupied_iou >= MIN_IOU
            and max(map(abs, self.origin_offset_cells)) <= MAX_ORIGIN_OFFSET_CELLS
            and self.path_relative_error <= MAX_PATH_RELATIVE_ERROR
            and self.min_clearance_m > ClearanceThresholds().d_safe
        )


def load_nav2_map(path: Path) -> OccupancyGrid:
    """Load a level, non-inverted trinary P5 map, treating unknown as occupied."""
    descriptor = _MapDescriptor.model_validate(
        load_yaml_document(path.read_bytes(), source=str(path))
    )
    if descriptor.free_thresh >= descriptor.occupied_thresh:
        msg = "the free threshold must be below the occupied threshold"
        raise ValueError(msg)
    base = path.resolve().parent
    image = (base / descriptor.image).resolve()
    if not image.is_relative_to(base):
        msg = "map image must stay inside the map directory"
        raise ValueError(msg)
    data = image.read_bytes()
    header = _PGM.match(data)
    if header is None:
        msg = f"{image}: expected an 8-bit binary PGM"
        raise ValueError(msg)
    width, height = (int(value) for value in header.groups())
    pixels = np.frombuffer(data, dtype=np.uint8, offset=header.end()).reshape(height, width)
    # PGM starts at the image's top-left. The occupancy grid starts at world bottom-left.
    blocked = np.flipud((_MAX_PIXEL - pixels) / _MAX_PIXEL >= descriptor.free_thresh)
    return OccupancyGrid(
        blocked, descriptor.resolution, (descriptor.origin[0], descriptor.origin[1])
    )


def _aligned_iou(reference: OccupancyGrid, clone: OccupancyGrid) -> tuple[float, tuple[int, int]]:
    if not math.isclose(reference.resolution, clone.resolution):
        msg = "occupancy alignment requires matching cell sizes"
        raise ValueError(msg)
    offset = (np.asarray(clone.origin) - np.asarray(reference.origin)) / reference.resolution
    rounded = np.rint(offset)
    if not np.allclose(offset, rounded, atol=_CELL_TOLERANCE, rtol=0):
        msg = "map origins are not aligned on whole cells"
        raise ValueError(msg)
    dx, dy = int(rounded[0]), int(rounded[1])
    top, left = max(0, dy), max(0, dx)
    bottom = min(reference.shape[0], dy + clone.shape[0])
    right = min(reference.shape[1], dx + clone.shape[1])
    intersection = 0
    if bottom > top and right > left:
        ref_overlap = reference.occupied[top:bottom, left:right]
        clone_overlap = clone.occupied[top - dy : bottom - dy, left - dx : right - dx]
        intersection = int(np.count_nonzero(ref_overlap & clone_overlap))
    union = int(np.count_nonzero(reference.occupied) + np.count_nonzero(clone.occupied))
    union -= intersection
    return (intersection / union if union else 1.0), (dx, dy)


def compare(
    nav2_map: OccupancyGrid,
    k2d_map: OccupancyGrid,
    nav2_path: npt.NDArray[np.float64],
    k2d_path: npt.NDArray[np.float64],
) -> Alignment:
    """Compare the aligned occupied cells and measure both world-space polylines."""
    iou, offset = _aligned_iou(nav2_map, k2d_map)
    path_m = polyline_length_m(nav2_path)
    k2d_path_m = polyline_length_m(k2d_path)
    if not (path_m > 0 and k2d_path_m > 0):
        msg = "both nominal paths must have positive length"
        raise ValueError(msg)
    min_clearance = min(
        float(np.min(nav2_map.distance_at(nav2_path))),
        float(np.min(k2d_map.distance_at(k2d_path))),
    )
    relative_error = abs(k2d_path_m - path_m) / path_m
    return Alignment(iou, offset, path_m, k2d_path_m, relative_error, min_clearance)


def main(argv: list[str] | None = None) -> int:
    """Compare the checked-in warehouse assets or use explicit file paths."""
    maps = REPO_ROOT / "configs/maps"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", type=Path, default=maps / "warehouse_v1.yaml")
    parser.add_argument("--k2d-world", type=Path, default=maps / "warehouse_v1_k2d.json")
    parser.add_argument("--nav2-path", type=Path, default=maps / "warehouse_v1_nominal_path.json")
    parser.add_argument(
        "--task", type=Path, default=REPO_ROOT / "tasks/warehouse_delivery_aligned_v1.yaml"
    )
    args = parser.parse_args(argv)
    task = load_task(args.task, strict=True)
    alignment = compare(
        load_nav2_map(args.map),
        load_world(args.k2d_world),
        np.asarray(json.loads(args.nav2_path.read_text(encoding="utf-8")), dtype=np.float64),
        load_nominal_path(args.task, task),
    )
    print(json.dumps(asdict(alignment), indent=2, sort_keys=True))
    return int(not alignment.passes())


if __name__ == "__main__":
    raise SystemExit(main())
