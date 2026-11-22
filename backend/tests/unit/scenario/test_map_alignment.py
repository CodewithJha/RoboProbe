"""Verify the checked-in Nav2 and kinematic warehouse assets (T-092)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from roboprobe.core.settings.oracles import ClearanceThresholds

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[4]


def test_warehouse_maps_and_nominal_paths_align() -> None:
    result = subprocess.run(  # noqa: S603 - fixed repository path and Python interpreter
        [sys.executable, str(ROOT / "scripts/compare_maps.py")],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    measurements = json.loads(result.stdout)
    assert measurements["occupied_iou"] >= 0.95
    assert max(map(abs, measurements["origin_offset_cells"])) <= 1
    assert measurements["path_relative_error"] <= 0.02
    assert measurements["min_clearance_m"] > ClearanceThresholds().d_safe
