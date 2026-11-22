"""Decode Nav2 PGM occupancy pixels for the kinematic and ROS distance kernels."""

from __future__ import annotations

import re

import numpy as np

from roboprobe.geometry.grid import OccupancyGrid

__all__ = ["decode_ros_pgm"]

_MAX_PIXEL = 255
_HEADER = re.compile(
    rb"P5\s*\n(?:#[^\n]*\n)*(?P<cols>\d+)\s+(?P<rows>\d+)\s+(?P<maxval>\d+)(?:\r\n|\s)"
)


def decode_ros_pgm(
    raw: bytes,
    *,
    resolution: float,
    origin: tuple[float, float],
    free_thresh: float,
    negate: bool,
) -> OccupancyGrid:
    """Build a metric grid from an 8-bit binary PGM in Nav2 trinary mode.

    PGM rows count from the top of the image. Grid rows count from the lower
    world coordinate. Unknown cells, like occupied cells, constrain clearance.
    """
    header = _HEADER.match(raw)
    if header is None or int(header["maxval"]) != _MAX_PIXEL:
        msg = "expected an 8-bit binary P5 PGM"
        raise ValueError(msg)
    cols, rows = int(header["cols"]), int(header["rows"])
    pixels = np.frombuffer(raw, dtype=np.uint8, offset=header.end())
    if cols < 1 or rows < 1 or pixels.size != cols * rows:
        msg = "PGM pixel payload size does not match its dimensions"
        raise ValueError(msg)
    if not 0.0 <= free_thresh <= 1.0:
        msg = "free_thresh must be between zero and one"
        raise ValueError(msg)

    gray = pixels.reshape(rows, cols).astype(np.float64) / _MAX_PIXEL
    probability = gray if negate else 1.0 - gray
    return OccupancyGrid(np.flipud(probability >= free_thresh), resolution, origin=origin)
