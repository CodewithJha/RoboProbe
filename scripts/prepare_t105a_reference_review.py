"""Verify an EXP-07 reference set and retain diagnostic traces for human review."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pyarrow.parquet as pq
from sklearn.cluster import HDBSCAN

from roboprobe.backends.kinematic2d.model import Kinematic2DModel
from roboprobe.core.settings import load_settings
from roboprobe.scenario.samplers import SobolSampler
from roboprobe.scenario.space import ScenarioSpace

REPO = Path(__file__).resolve().parents[1]
REFERENCE_N = 20_000
REFERENCE_SEED = 20261119
REVIEW_FRACTIONS = (0.10, 0.50, 0.90)
SPACE_IDS = ("warehouse_v1", "warehouse_v1_d8", "warehouse_v1_noise2")


def _verify(
    raw: Path, space_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]], npt.NDArray[np.float64]]:
    space = ScenarioSpace.from_yaml(
        REPO / "configs/scenario_spaces" / f"{space_id}.yaml", base_dir=REPO
    )
    manifest = json.loads(raw.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    model_path = REPO / load_settings().backends.kinematic2d.model_file
    expected = {
        "n": REFERENCE_N,
        "seed": REFERENCE_SEED,
        "space_id": space.id,
        "space_version": space.version,
        "k2d_model_version": Kinematic2DModel.from_yaml(model_path).id,
        "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
    }
    if any(manifest[key] != value for key, value in expected.items()):
        message = "Reference manifest does not match the frozen sampling or the raw Parquet"
        raise ValueError(message)
    rows = pq.read_table(raw).to_pylist()
    if len(rows) != REFERENCE_N or any(row["ordinal"] != i for i, row in enumerate(rows)):
        message = "Reference rows are incomplete or out of order"
        raise ValueError(message)
    if any(row["gt_label"] is not None for row in rows):
        message = "A raw reference must have no reviewed ground-truth labels"
        raise ValueError(message)
    unit = np.asarray([[row[f"u{i}"] for i in range(space.dim)] for row in rows])
    expected_unit = SobolSampler(space.dim).sample(
        REFERENCE_N, np.random.default_rng(REFERENCE_SEED)
    )
    np.testing.assert_array_equal(unit, expected_unit)
    return manifest, rows, unit


def _candidate_indices(
    rows: list[dict[str, Any]], unit: npt.NDArray[np.float64]
) -> tuple[dict[int, int], dict[tuple[int, str], list[int]]]:
    fails = np.asarray([i for i, row in enumerate(rows) if row["verdict"] == "FAIL"])
    if not fails.size:
        return {}, {}
    classes = [str(rows[i]["primary_failure"]) for i in fails]
    categories = {label: i for i, label in enumerate(sorted(set(classes)))}
    analysis = load_settings().analysis
    settings = analysis.hdbscan
    min_size = max(
        settings.min_cluster_size_floor, math.ceil(settings.min_cluster_fraction * len(fails))
    )
    class_features = np.eye(len(categories))[[categories[label] for label in classes]]
    x = np.column_stack(
        (
            unit[fails] * analysis.feature_weights.param,
            class_features * analysis.feature_weights.class_,
        )
    )
    labels = (
        HDBSCAN(min_cluster_size=min_size, min_samples=min_size, n_jobs=1).fit_predict(x)
        if len(fails) >= min_size
        else np.full(len(fails), -1)
    )
    assignments = {int(i): int(cluster) for i, cluster in zip(fails, labels, strict=True)}
    groups: dict[tuple[int, str], list[int]] = {}
    for i, label in zip(fails, classes, strict=True):
        groups.setdefault((assignments[int(i)], label), []).append(int(i))
    return assignments, groups


def main() -> None:
    """Write candidate assignments and representative traces without assigning GT labels."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--trace-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--space", choices=SPACE_IDS, required=True)
    args = parser.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    trace_root: Path = args.trace_root
    manifest, rows, unit = _verify(args.reference, args.space)
    assignments, groups = _candidate_indices(rows, unit)
    trace_evidence: list[dict[str, str | int]] = []
    for (cluster, primary), group in sorted(groups.items()):
        by_robustness = sorted(group, key=lambda i: (rows[i]["robustness"], i))
        indices = sorted({by_robustness[round((len(group) - 1) * p)] for p in REVIEW_FRACTIONS})
        for i in indices:
            folder = out / "representative-traces" / f"ref-{i}"
            folder.mkdir(parents=True, exist_ok=True)
            for filename in ("trace.parquet", "episode.log", "obstacle.json", "world.json"):
                shutil.copyfile(trace_root / f"ref-{i}" / filename, folder / filename)
            trace_evidence.append(
                {
                    "ordinal": i,
                    "candidate_cluster": cluster,
                    "primary_failure": primary,
                    "trace_sha256": hashlib.sha256(
                        (folder / "trace.parquet").read_bytes()
                    ).hexdigest(),
                }
            )
    result = {
        "manifest": manifest,
        "verdict_counts": dict(Counter(row["verdict"] for row in rows)),
        "reviewed_ground_truth_labels": 0,
        "candidate_method": "HDBSCAN on weighted unit coordinates and primary-failure class",
        "candidate_cluster_by_ordinal": assignments,
        "representative_traces": trace_evidence,
    }
    (out / "review-candidates.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{args.space}: verified {len(rows)} rows, retained {len(trace_evidence)} traces")


if __name__ == "__main__":
    main()
