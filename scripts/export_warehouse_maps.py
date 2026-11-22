#!/usr/bin/env python3
"""Export ``warehouse_v1`` maps and nominal path artefacts (T-092).

Writes ``tasks/maps/warehouse.{yaml,pgm}`` from the kinematic2d clone, copies the vendored
Nav2 warehouse map to ``configs/maps/warehouse_v1.*``, and stores the A* nominal path.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import numpy.typing as npt

from roboprobe.backends.kinematic2d.model import Kinematic2DModel
from roboprobe.backends.kinematic2d.planner import plan_path
from roboprobe.backends.kinematic2d.world import load_world
from roboprobe.scenario.map_io import write_ros_map


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _write_nominal_path(root: Path, points: npt.NDArray[np.float64]) -> None:
    csv_path = root / "tasks" / "paths" / "warehouse_delivery_v1.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["x", "y"])
        writer.writerows([[f"{x:.2f}", f"{y:.2f}"] for x, y in points])
    json_path = root / "configs" / "maps" / "warehouse_v1_nominal_path.json"
    json_path.write_text(json.dumps(points.tolist(), indent=2) + "\n", encoding="utf-8")


def main() -> int:
    """Export warehouse maps and nominal path under the repository root."""
    root = _repo_root()
    model = Kinematic2DModel.from_yaml(root / "configs/backends/kinematic2d_v1.yaml")
    grid = load_world(root / "configs/backends/warehouse_k2d.json")
    write_ros_map(root / "tasks/maps/warehouse.yaml", grid)

    nav_yaml = root / "configs/maps/warehouse_v1.yaml"
    nav_pgm = root / "configs/maps/warehouse_v1.pgm"
    nav_yaml.parent.mkdir(parents=True, exist_ok=True)
    if not nav_pgm.is_file():
        msg = f"missing vendored Gazebo map: {nav_pgm}"
        print(msg, file=sys.stderr)
        return 2
    if not nav_yaml.is_file():
        msg = f"missing vendored Gazebo map metadata: {nav_yaml}"
        print(msg, file=sys.stderr)
        return 2

    start = (model.world.start_x_m, model.world.start_y_m)
    goal = (model.world.goal_x_m, model.world.goal_y_m)
    path = plan_path(grid, start, goal)
    if path is None:
        print("Planner returned no path for warehouse task", file=sys.stderr)
        return 1
    _write_nominal_path(root, path)
    print("Exported tasks/maps/warehouse.*, configs/maps/warehouse_v1.*, nominal path")
    return 0


if __name__ == "__main__":
    sys.exit(main())
