"""Recompute warehouse discovery metrics from versioned, reviewed evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from roboprobe.bootstrap.reference_scoring import score_reference
from roboprobe.bootstrap.reference_set import ReferenceManifest, sha256_file, write_manifest
from roboprobe.core.errors import ValidationError

pytestmark = pytest.mark.unit
SPACE = "warehouse_v1_d8"
VERSION = "test_space"
MODEL = "test_model"
DESIGN = Path(__file__).resolve().parents[4] / "configs/experiments/exp07_scalability_d8.yaml"
BUDGET = 300


def _coordinates(first: float, last: float = 0.0) -> list[float]:
    return [first, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, last]


def _run(ordinal: int, first: float, last: float = 0.0, **overrides: object) -> dict[str, object]:
    return {
        "strategy": "S-PROBE",
        "experiment_rep": 5,
        "ordinal": ordinal,
        "verdict": "FAIL",
        "is_comparison_run": True,
        "x_unit": _coordinates(first, last),
        **overrides,
    }


def _inputs(
    root: Path, *, labels: dict[int, str | None], runs: list[dict[str, object]] | None = None
) -> tuple[Path, Path, Path, Path]:
    names = ("runs.parquet", "runs.manifest.json", "reference.parquet", "review.json")
    raw, manifest, reference, review = (root / name for name in names)
    runs = runs or [
        _run(BUDGET, 0.251, 0.8),
        _run(2, 0.28, 0.8, is_comparison_run=False),
        _run(1, 0.241),
        _run(0, 0.25, verdict="PASS"),
        _run(3, 0.9),
        *(_run(i, 0.0, verdict="PASS") for i in range(4, BUDGET)),
    ]
    pq.write_table(pa.Table.from_pylist(runs), raw)
    manifest.write_text(
        json.dumps(
            {
                "sha256": sha256_file(raw),
                "config_sha256": sha256_file(DESIGN),
                "design_id": "exp07_d8",
                "backend": "kinematic2d",
                "space_id": SPACE,
                "space_version": VERSION,
                "k2d_model_version": MODEL,
                "budget": BUDGET,
            }
        ),
        encoding="utf-8",
    )
    points = [_coordinates(0.25), _coordinates(0.28, 0.8), _coordinates(0.242), _coordinates(0.9)]
    table = pa.table(
        {
            "ordinal": range(len(points)),
            "verdict": ["FAIL", "FAIL", "FAIL", "PASS"],
            **{f"u{i}": values for i, values in enumerate(zip(*points, strict=True))},
        }
    )
    pq.write_table(table, reference)
    ref_digest = sha256_file(reference)
    write_manifest(
        reference.with_suffix(".manifest.json"),
        ReferenceManifest(reference.name, ref_digest, len(points), 11, SPACE, VERSION, MODEL),
    )
    review.write_text(json.dumps({"source_sha256": ref_digest, "labels": labels}), encoding="utf-8")
    return raw, manifest, reference, review


@pytest.mark.parametrize("reviewed", [True, False])
def test_discovery_scores_use_full_coordinates_and_nearest_review(
    tmp_path: Path, reviewed: bool
) -> None:
    """An explicit null differs from an omitted review at the nearest reference row."""
    labels: dict[int, str | None] = {0: "GT-A", 1: "GT-B"}
    if reviewed:
        labels[2] = None
    paths = _inputs(tmp_path, labels=labels)
    score = score_reference(*paths)
    assert score["review_sha256"] == sha256_file(paths[-1])
    assert score["mode_match_radius"] == 0.05
    assert score["canonical_modes"] == ["GT-A", "GT-B"]
    assert score["unreviewed_reference_failures"] == (0 if reviewed else 1)
    (cell,) = cast("list[dict[str, Any]]", score["cells"])
    assert cell["modes"] == ["GT-B"]
    assert cell["novel_failures"] == 1
    assert cell["unreviewed_matches"] == (0 if reviewed else 1)
    assert cell["met_02"] == (1 if reviewed else None)
    assert cell["met_09"] == (pytest.approx(1 / (BUDGET * 2)) if reviewed else None)


def test_incomplete_cell_has_no_final_metrics(tmp_path: Path) -> None:
    """Do not extend an incomplete campaign into a complete registered-budget sample."""
    raw, manifest, reference, review = _inputs(
        tmp_path, labels={0: "GT-A", 1: "GT-B", 2: None}, runs=[_run(0, 0.25)]
    )
    (cell,) = cast(
        "list[dict[str, Any]]", score_reference(raw, manifest, reference, review)["cells"]
    )
    assert cell["modes"] == ["GT-A"]
    assert cell["comparison_runs"] == 1
    assert cell["met_02"] is None
    assert cell["met_09"] is None


@pytest.mark.parametrize(
    ("artifact", "field", "value"),
    [
        ("runs", "sha256", "0" * 64),
        ("runs", "config_sha256", "0" * 64),
        ("runs", "budget", 1),
        ("runs", "space_version", "other-version"),
        ("runs", "k2d_model_version", "other-model"),
        ("review", "source_sha256", "0" * 64),
        ("review", "labels", {"3": "GT-A"}),
    ],
)
def test_rejects_foreign_or_invalid_provenance(
    tmp_path: Path, artifact: str, field: str, value: object
) -> None:
    pilot = [_run(0, 0.25)] if field == "budget" else None
    raw, manifest, reference, review = _inputs(tmp_path, labels={0: "GT-A"}, runs=pilot)
    path = manifest if artifact == "runs" else review
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError):
        score_reference(raw, manifest, reference, review)
