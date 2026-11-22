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

from roboprobe.backends.kinematic2d.world import load_world
from roboprobe.core.settings import load_settings
from roboprobe.scenario.map_io import load_ros_map, occupancy_iou


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    """Run the map comparison CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("k2d_json", type=Path, help="RLE occupancy JSON (warehouse_k2d)")
    parser.add_argument("ros_yaml", type=Path, help="ROS map YAML (Gazebo reference)")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args(argv)

    root = _repo_root()
    k2d = load_world(root / args.k2d_json)
    gazebo = load_ros_map(root / args.ros_yaml)
    result = occupancy_iou(k2d, gazebo)
    gates = load_settings().scenario.map_alignment
    payload = {
        "iou": result.iou,
        "agreement": result.agreement,
        "samples": result.samples,
        "min_iou": gates.min_iou,
        "pass": result.iou >= gates.min_iou,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        status = "PASS" if payload["pass"] else "FAIL"
        print(
            f"{status}: IoU={result.iou:.4f} agreement={result.agreement:.4f} "
            f"(gate {gates.min_iou})"
        )
    return 0 if payload["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
