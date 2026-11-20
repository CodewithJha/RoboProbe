"""Warehouse occupancy clone, RLE JSON loader and nominal path (docs/10 §7.1, docs/06 §1).

Layout approximates ``nav2_minimal_tb4_sim/worlds/warehouse.sdf``: outer walls and two
shelf blocks flanking a north-south aisle whose centre is Dock A ``x=2.12``. Coordinates
match the task start pose so they carry over to Gazebo (T-092).

Implements: FR-SIM-001
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from roboprobe.backends.kinematic2d.model import Kinematic2DModel, WorldModel
from roboprobe.core import errors
from roboprobe.geometry import OccupancyGrid

__all__ = [
    "WORLD_JSON_SCHEMA_VERSION",
    "build_warehouse_occupied",
    "dump_world_json",
    "load_world",
    "nominal_path_polyline",
    "rle_decode",
    "rle_encode",
    "world_document",
]

WORLD_JSON_SCHEMA_VERSION = 1
_OCCUPIED = 1
_FREE = 0


def _shape(spec: WorldModel) -> tuple[int, int]:
    cols = round(spec.width_m / spec.resolution_m)
    rows = round(spec.height_m / spec.resolution_m)
    return rows, cols


def _fill_rect(  # noqa: PLR0913,PLR0917
    occupied: npt.NDArray[np.bool_],
    spec: WorldModel,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> None:
    """Mark the axis-aligned rectangle ``[x0,x1) x [y0,y1)`` occupied."""
    origin = np.array([spec.origin_x_m, spec.origin_y_m])
    lo = np.floor((np.array([x0, y0]) - origin) / spec.resolution_m).astype(int)
    hi = np.ceil((np.array([x1, y1]) - origin) / spec.resolution_m).astype(int)
    rows, cols = occupied.shape
    c0, r0 = int(np.clip(lo[0], 0, cols)), int(np.clip(lo[1], 0, rows))
    c1, r1 = int(np.clip(hi[0], 0, cols)), int(np.clip(hi[1], 0, rows))
    occupied[r0:r1, c0:c1] = True


def build_warehouse_occupied(spec: WorldModel) -> npt.NDArray[np.bool_]:
    """Boolean occupancy of the warehouse clone (walls + two shelf blocks)."""
    occupied = np.zeros(_shape(spec), dtype=np.bool_)
    ox, oy = spec.origin_x_m, spec.origin_y_m
    x1, y1 = ox + spec.width_m, oy + spec.height_m
    t = spec.wall_thickness_m
    _fill_rect(occupied, spec, ox, oy, x1, oy + t)
    _fill_rect(occupied, spec, ox, y1 - t, x1, y1)
    _fill_rect(occupied, spec, ox, oy, ox + t, y1)
    _fill_rect(occupied, spec, x1 - t, oy, x1, y1)
    left_x1 = spec.aisle_x_m - spec.aisle_half_width_m
    right_x0 = spec.aisle_x_m + spec.aisle_half_width_m
    _fill_rect(occupied, spec, ox + t, spec.shelf_y0_m, left_x1, spec.shelf_y1_m)
    _fill_rect(occupied, spec, right_x0, spec.shelf_y0_m, x1 - t, spec.shelf_y1_m)
    return occupied


def rle_encode(occupied: npt.NDArray[np.bool_]) -> list[list[int]]:
    """Row-major run-length encoding ``[[value, count], ...]`` with value in ``{0,1}``."""
    flat = occupied.ravel()
    if flat.size == 0:
        return []
    runs: list[list[int]] = []
    value = int(flat[0])
    count = 1
    for cell in flat[1:]:
        bit = int(cell)
        if bit == value:
            count += 1
        else:
            runs.append([value, count])
            value, count = bit, 1
    runs.append([value, count])
    return runs


def rle_decode(runs: list[list[int]], shape: tuple[int, int]) -> npt.NDArray[np.bool_]:
    """Invert :func:`rle_encode`."""
    rows, cols = shape
    size = rows * cols
    flat = np.empty(size, dtype=np.bool_)
    cursor = 0
    for value, count in runs:
        if value not in (_FREE, _OCCUPIED) or count < 1 or cursor + count > size:
            msg = "invalid occupancy RLE"
            raise errors.ValidationError(msg, context={"cursor": cursor, "count": count})
        flat[cursor : cursor + count] = bool(value)
        cursor += count
    if cursor != size:
        msg = f"RLE covers {cursor} cells, expected {size}"
        raise errors.ValidationError(msg, context={"cursor": cursor, "size": size})
    return flat.reshape(shape)


def world_document(model: Kinematic2DModel) -> dict[str, Any]:
    """Canonical JSON-serialisable warehouse world (byte-stable with ``sort_keys``)."""
    spec = model.world
    occupied = build_warehouse_occupied(spec)
    rows, cols = occupied.shape
    return {
        "id": "warehouse_k2d",
        "origin": [spec.origin_x_m, spec.origin_y_m],
        "provenance": (
            "Hand-built occupancy clone of nav2_minimal_tb4_sim/worlds/warehouse.sdf; "
            "start pose docs/06 §1 Dock A."
        ),
        "resolution": spec.resolution_m,
        "rle": rle_encode(occupied),
        "schema_version": WORLD_JSON_SCHEMA_VERSION,
        "shape": [rows, cols],
    }


def dump_world_json(model: Kinematic2DModel) -> str:
    """Deterministic JSON text (sorted keys, compact separators, trailing newline)."""
    return json.dumps(world_document(model), sort_keys=True, separators=(",", ":")) + "\n"


def load_world(path: Path) -> OccupancyGrid:
    """Load an RLE occupancy JSON file.

    Raises:
        roboprobe.core.errors.NotFoundError: Missing file.
        roboprobe.core.errors.ValidationError: Malformed document.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        msg = f"world not found: {path}"
        raise errors.NotFoundError(msg, context={"path": str(path)}) from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"{path}: invalid JSON: {exc}"
        raise errors.ValidationError(msg, context={"path": str(path)}) from exc
    version_ok = isinstance(document, dict) and document.get("schema_version") == (
        WORLD_JSON_SCHEMA_VERSION
    )
    if not version_ok:
        msg = f"{path}: expected schema_version {WORLD_JSON_SCHEMA_VERSION}"
        raise errors.ValidationError(msg, context={"path": str(path)})
    origin = document["origin"]
    shape = tuple(document["shape"])
    occupied = rle_decode(list(document["rle"]), (int(shape[0]), int(shape[1])))
    return OccupancyGrid(
        occupied,
        float(document["resolution"]),
        origin=(float(origin[0]), float(origin[1])),
    )


def nominal_path_polyline(spec: WorldModel) -> npt.NDArray[np.float64]:
    """Straight aisle polyline from Dock A to Station B (matches the provisional task CSV)."""
    y0, y1 = spec.start_y_m, spec.goal_y_m
    step = spec.resolution_m
    n = round(abs(y1 - y0) / step) + 1
    ys = np.linspace(y0, y1, n)
    xs = np.full(n, spec.start_x_m)
    return np.column_stack([xs, ys])
