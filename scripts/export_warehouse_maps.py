#!/usr/bin/env python3
"""Export ``warehouse_v1`` maps and nominal path artefacts (T-092).

Rebuilds the legacy ROS export, aligned occupancy JSON and task path CSV from the checked-in
warehouse map and the measured Nav2 path.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from roboprobe.backends.kinematic2d.world import WORLD_JSON_SCHEMA_VERSION, load_world, rle_encode
from roboprobe.scenario.map_io import load_ros_map, write_ros_map


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _write_task_path(root: Path) -> None:
    json_path = root / "configs" / "maps" / "warehouse_v1_nominal_path.json"
    points = json.loads(json_path.read_text(encoding="utf-8"))
    csv_path = root / "tasks" / "paths" / "warehouse_v1_nominal_path.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["x", "y"])
        writer.writerows(points)


def main() -> int:
    """Export warehouse maps and nominal path under the repository root."""
    root = _repo_root()
    legacy_grid = load_world(root / "configs/backends/warehouse_k2d.json")
    write_ros_map(root / "tasks/maps/warehouse.yaml", legacy_grid)
    aligned = load_ros_map(root / "configs/maps/warehouse_v1.yaml")
    document = {
        "id": "warehouse_v1_k2d",
        "origin": list(aligned.origin),
        "provenance": (
            "Pinned Nav2 warehouse map; unknown and occupied cells conservatively block motion."
        ),
        "resolution": aligned.resolution,
        "rle": rle_encode(aligned.occupied),
        "schema_version": WORLD_JSON_SCHEMA_VERSION,
        "shape": list(aligned.shape),
    }
    (root / "configs/maps/warehouse_v1_k2d.json").write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    _write_task_path(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
