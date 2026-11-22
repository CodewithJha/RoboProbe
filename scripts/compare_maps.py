#!/usr/bin/env python3
r"""Compare occupancy between the kinematic2d world JSON and a ROS map (T-092).

Usage (repo root)::

    uv run --directory backend python ../scripts/compare_maps.py \\
        configs/backends/warehouse_k2d.json configs/maps/warehouse_v1.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from roboprobe.backends.kinematic2d.world import load_world
from roboprobe.core.settings import load_settings
from roboprobe.scenario.map_io import load_ros_map, occupancy_iou
from roboprobe.scenario.task import load_nominal_path, load_task, polyline_length_m

_MAX_ORIGIN_OFFSET_CELLS = 1


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    """Run the map comparison CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "k2d_json", nargs="?", type=Path, default=Path("configs/maps/warehouse_v1_k2d.json")
    )
    parser.add_argument(
        "ros_yaml", nargs="?", type=Path, default=Path("configs/maps/warehouse_v1.yaml")
    )
    parser.add_argument(
        "--nav2-path", type=Path, default=Path("configs/maps/warehouse_v1_nominal_path.json")
    )
    parser.add_argument(
        "--task", type=Path, default=Path("tasks/warehouse_delivery_aligned_v1.yaml")
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args(argv)

    root = _repo_root()
    k2d = load_world(root / args.k2d_json)
    gazebo = load_ros_map(root / args.ros_yaml)
    result = occupancy_iou(k2d, gazebo)
    task_file = root / args.task
    k2d_path = load_nominal_path(task_file, load_task(task_file, strict=True))
    nav2_path = np.asarray(
        json.loads((root / args.nav2_path).read_text(encoding="utf-8")), dtype=np.float64
    )
    nav2_length = polyline_length_m(nav2_path)
    if not nav2_length > 0:
        msg = "Nav2 nominal path must have positive length"
        raise ValueError(msg)
    k2d_length = polyline_length_m(k2d_path)
    path_error = abs(nav2_length - k2d_length) / nav2_length
    clearance = min(
        float(np.min(gazebo.distance_at(nav2_path))), float(np.min(k2d.distance_at(k2d_path)))
    )
    offset = np.abs(np.asarray(k2d.origin) - np.asarray(gazebo.origin)) / gazebo.resolution
    settings = load_settings()
    gates = settings.scenario.map_alignment
    passes = (
        result.iou >= gates.min_iou
        and float(np.max(offset)) <= _MAX_ORIGIN_OFFSET_CELLS
        and path_error <= gates.path_length_tolerance_ratio
        and clearance > settings.oracles.clear.d_safe
    )
    payload = {
        "iou": result.iou,
        "agreement": result.agreement,
        "samples": result.samples,
        "min_iou": gates.min_iou,
        "origin_offset_cells": offset.tolist(),
        "nav2_path_m": nav2_length,
        "k2d_path_m": k2d_length,
        "path_relative_error": path_error,
        "min_clearance_m": clearance,
        "pass": passes,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        status = "PASS" if payload["pass"] else "FAIL"
        print(
            f"{status}: IoU={result.iou:.4f} agreement={result.agreement:.4f} "
            f"(gate {gates.min_iou}), origin offset {offset.tolist()} cells, "
            f"paths {nav2_length:.3f} m / {k2d_length:.3f} m, clearance {clearance:.3f} m"
        )
    return 0 if payload["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
