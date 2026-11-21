"""Reference set generation and labelling (T-103)."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from roboprobe.backends.kinematic2d.calibration import load_calibration
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import Verdict
from roboprobe.experiments.reference_set import (
    generate_rows,
    label_rows,
    sha256_file,
    write_parquet,
)
from roboprobe.scenario.space import ScenarioSpace

pytestmark = [pytest.mark.unit, pytest.mark.slow]

REPO = Path(__file__).resolve().parents[4]


def _settings() -> RoboProbeSettings:
    return RoboProbeSettings(
        backends={
            "kinematic2d": {
                "model_file": str(REPO / "configs/backends/kinematic2d_v1.yaml"),
                "perception_model_file": str(REPO / "configs/perception/oakd_k2d_v1.yaml"),
                "calibration_file": str(REPO / "configs/reference/k2d_gt_canonical.yaml"),
            }
        }
    )


def test_generate_label_and_hash(tmp_path: Path) -> None:
    space = ScenarioSpace.from_yaml(
        REPO / "configs/scenario_spaces/warehouse_v1.yaml", base_dir=REPO
    )
    rows = generate_rows(
        space,
        _settings(),
        n=8,
        seed=11,
        repo_root=REPO,
        workdir=tmp_path / "runs",
    )
    assert len(rows) == 8
    verdicts = {row["verdict"] for row in rows}
    allowed = {Verdict.PASS.value, Verdict.FAIL.value, Verdict.INVALID.value}
    assert verdicts <= allowed
    calibration = load_calibration(REPO / "configs/reference/k2d_gt_canonical.yaml")
    label_rows(rows, calibration, radius=0.05)
    path = tmp_path / "ref.parquet"
    write_parquet(path, rows)
    assert sha256_file(path) == sha256_file(path)
    reread = pq.read_table(path).to_pylist()
    assert len(reread) == 8
