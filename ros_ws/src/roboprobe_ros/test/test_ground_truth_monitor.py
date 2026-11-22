"""Validate ground-truth clearance and attitude using known fixtures (T-094a)."""

# ruff: noqa: S101

from __future__ import annotations

from math import pi, sqrt
from typing import TYPE_CHECKING

import numpy as np
import pytest
import yaml
from roboprobe_ros._vendor.geometry import OccupancyGrid, PolygonFootprint, Rect
from roboprobe_ros.ground_truth_monitor import GroundTruthMonitor

if TYPE_CHECKING:
    from pathlib import Path

_HALF_TURN_COMPONENT = sqrt(0.5)
_NO_ROTATION = (0.0, 0.0, 0.0, 1.0)


@pytest.fixture
def monitor() -> GroundTruthMonitor:
    """A small map with one wall and a separate analytic rectangle."""
    occupied = np.zeros((12, 12), dtype=np.bool_)
    occupied[0, :] = True
    grid = OccupancyGrid(occupied, 1.0)
    footprint = PolygonFootprint(
        np.array([[-0.25, -0.25], [0.25, -0.25], [0.25, 0.25], [-0.25, 0.25]])
    )
    pallet = Rect(x=8.0, y=5.0, yaw=0.0, length=2.0, width=1.0)
    return GroundTruthMonitor(footprint, grid, [pallet])


@pytest.mark.parametrize(
    ("position", "clearance"),
    [
        ((5.0, 5.0), 1.75),  # Analytic distance from the robot's edge to the pallet.
        ((8.0, 5.0), 0.0),  # Footprint overlaps the pallet.
        ((5.0, 1.5), 0.5),  # Nearest wall cell is one metre away, minus half a cell.
        ((5.0, -0.2), 0.0),  # Part of the footprint lies outside the map.
    ],
)
def test_clearance(
    monitor: GroundTruthMonitor, position: tuple[float, float], clearance: float
) -> None:
    """Distances include the actual robot footprint, map bounds and pallet."""
    assert monitor.evaluate(position, _NO_ROTATION).clearance_m == pytest.approx(clearance)


@pytest.mark.parametrize("sign", [-1.0, 1.0])
def test_roll_and_pitch_at_right_angles(monitor: GroundTruthMonitor, sign: float) -> None:
    """Roll and pitch recover stable ±90° values after quaternion normalization."""
    q = _HALF_TURN_COMPONENT * 3.0  # Simulate a valid rotation arriving with a scaled quaternion.
    roll = monitor.evaluate((5.0, 5.0), (sign * q, 0.0, 0.0, q))
    pitch = monitor.evaluate((5.0, 5.0), (0.0, sign * q, 0.0, q))
    assert roll.roll_rad == pytest.approx(sign * pi / 2)
    assert roll.pitch_rad == pytest.approx(0.0)
    assert pitch.roll_rad == pytest.approx(0.0)
    assert pitch.pitch_rad == pytest.approx(sign * pi / 2)


def test_invalid_orientation(monitor: GroundTruthMonitor) -> None:
    """Reject a degenerate quaternion rather than treating it as a safe pose."""
    with pytest.raises(ValueError, match="quaternion"):
        monitor.evaluate((5.0, 5.0), (0.0, 0.0, 0.0, 0.0))


def test_load_generated_file(tmp_path: Path) -> None:
    """Load the PGM with top-first rows and the typed footprint and pallet records."""
    values = np.full((12, 12), 255, dtype=np.uint8)
    values[-1] = 0  # Bottom of the PGM is the world wall at row zero.
    map_root = tmp_path / "maps"
    map_root.mkdir()
    (map_root / "warehouse.pgm").write_bytes(b"P5\n12 12\n255\n" + values.tobytes())
    (map_root / "warehouse.yaml").write_text(
        "image: warehouse.pgm\nresolution: 1.0\norigin: [0, 0, 0]\nfree_thresh: 0.2\n",
        encoding="utf-8",
    )
    episode = tmp_path / "episode.yaml"
    document = {
        "map_file": "maps/warehouse.yaml",
        "footprint": {"radius_m": 0.25},
        "pallets": [{"pose": {"x": 8.0, "y": 5.0, "yaw": 0.0}, "size": [2.0, 1.0, 0.135]}],
    }
    episode.write_text(yaml.safe_dump(document), encoding="utf-8")
    loaded = GroundTruthMonitor.from_episode(episode)
    assert loaded.evaluate((5.0, 5.0), _NO_ROTATION).clearance_m == pytest.approx(1.75)
    assert loaded.evaluate((5.0, 1.5), _NO_ROTATION).clearance_m == pytest.approx(0.25)


def test_map_file_must_stay_in_episode(tmp_path: Path) -> None:
    """Reject an episode attempting to read a map outside its workspace."""
    episode = tmp_path / "episode.yaml"
    episode.write_text("map_file: ../external.yaml\n", encoding="utf-8")
    with pytest.raises(ValueError, match="map_file must stay inside"):
        GroundTruthMonitor.from_episode(episode)
