"""Reference set generation and labelling (T-103)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from roboprobe.backends.kinematic2d.calibration import load_calibration
from roboprobe.bootstrap.reference_set import (
    ReferenceManifest,
    generate_rows,
    label_parquet,
    label_rows,
    sha256_file,
    write_manifest,
    write_parquet,
)
from roboprobe.core.errors import ValidationError
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import Verdict
from roboprobe.scenario.space import ScenarioSpace

pytestmark = pytest.mark.unit

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


def test_reference_cli_outputs_matching_parquet_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented command writes an integrity manifest and returns it as JSON."""
    monkeypatch.setenv("ROBOPROBE_STORAGE__WORKDIR_ROOT", str(tmp_path / "runs"))
    out = tmp_path / "reference.parquet"
    result = subprocess.run(  # noqa: S603 - this is the tested CLI in an isolated interpreter.
        [
            sys.executable,
            "-c",
            "from roboprobe.cli.main import app; app()",
            "--json",
            "reference",
            "generate",
            "--output",
            str(out),
            "--n",
            "1",
            "--seed",
            "11",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    manifest = json.loads(out.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    assert json.loads(result.stdout) == manifest
    assert manifest["path"] == str(out)
    assert manifest["sha256"] == sha256_file(out)
    assert pq.read_table(out).num_rows == manifest["n"] == 1
    assert manifest["seed"] == 11


def test_reviewed_labels_preserve_digest_and_unassigned_failures(tmp_path: Path) -> None:
    """Bind reviewed mode assignments to the raw dataset and stamp the labelled output."""
    source = tmp_path / "raw.parquet"
    rows = [
        {"ordinal": 0, "verdict": "FAIL", "gt_label": None},
        {"ordinal": 1, "verdict": "PASS", "gt_label": None},
        {"ordinal": 2, "verdict": "FAIL", "gt_label": None},
    ]
    write_parquet(source, rows)
    source_digest = sha256_file(source)
    write_manifest(
        source.with_suffix(".manifest.json"),
        ReferenceManifest(str(source), source_digest, len(rows), 11, "warehouse_v1", "abc", "k2d"),
    )
    reviewed = tmp_path / "review.json"
    reviewed.write_text(
        json.dumps({"source_sha256": source_digest, "labels": {"0": "GT-A"}}), encoding="utf-8"
    )
    target = tmp_path / "labelled.parquet"
    assert label_parquet(_settings(), source, output=target, reviewed_labels=reviewed) == (
        target,
        1,
    )
    assert pq.read_table(target)["gt_label"].to_pylist() == ["GT-A", None, None]
    assert sha256_file(source) == source_digest
    manifest = json.loads(target.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    assert manifest["sha256"] == sha256_file(target)
    assert manifest["path"] == str(target)
    assert manifest["n"] == len(rows)


@pytest.mark.parametrize("wrong_digest", [False, True])
def test_rejects_mismatched_review_or_pass_label(tmp_path: Path, wrong_digest: bool) -> None:
    """Reject foreign datasets and assignments to passing rows before creating output."""
    source = tmp_path / "raw.parquet"
    write_parquet(source, [{"ordinal": 0, "verdict": "PASS", "gt_label": None}])
    reviewed = tmp_path / "review.json"
    digest = "0" * 64 if wrong_digest else sha256_file(source)
    reviewed.write_text(
        json.dumps({"source_sha256": digest, "labels": {"0": "GT-A"}}), encoding="utf-8"
    )
    target = tmp_path / "labelled.parquet"
    with pytest.raises(ValidationError, match="digest" if wrong_digest else "failing reference"):
        label_parquet(_settings(), source, output=target, reviewed_labels=reviewed)
    assert not target.exists()


def test_reference_keeps_all_dimensions(tmp_path: Path) -> None:
    """Record all eight free coordinates of the EXP-07 warehouse space."""
    space = ScenarioSpace.from_yaml(
        REPO / "configs/scenario_spaces/warehouse_v1_d8.yaml", base_dir=REPO
    )
    (row,) = generate_rows(space, _settings(), n=1, seed=11, repo_root=REPO, workdir=tmp_path)
    assert [key for key in row if key.startswith("u")] == [f"u{i}" for i in range(8)]
