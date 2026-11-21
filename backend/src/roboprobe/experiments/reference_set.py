"""Dense kinematic2d reference set for MET-02/MET-08 (T-103, docs/19 §3).

Implements: FR-EXP-001, MET-02, MET-08
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from roboprobe.backends.base import EpisodeRequest, episode_timeouts
from roboprobe.backends.kinematic2d.backend import Kinematic2DBackend
from roboprobe.backends.kinematic2d.calibration import K2DGtCalibration
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import Scenario, SutProfile, Verdict
from roboprobe.metrics.discovery_metrics import NOVEL_LABEL, label_failures
from roboprobe.oracles.registry import create_all
from roboprobe.oracles.verdict import VerdictEngine
from roboprobe.scenario.hashing import scenario_hash
from roboprobe.scenario.samplers import SobolSampler
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.task import load_task

__all__ = [
    "ReferenceManifest",
    "generate_rows",
    "label_rows",
    "sha256_file",
    "write_manifest",
    "write_parquet",
]

_REFERENCE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ReferenceManifest:
    """Content hash metadata for a reference artefact (docs/11 §6)."""

    path: str
    sha256: str
    n: int
    seed: int
    space_id: str
    space_version: str
    k2d_model_version: str


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of ``path``."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scenario(space: ScenarioSpace, values: Mapping[str, Any]) -> Scenario:
    return Scenario(
        space_id=space.id,
        space_version=space.version,
        values=dict(values),
        scenario_hash=scenario_hash(space.version, dict(values)),
    )


def generate_rows(  # noqa: PLR0913
    space: ScenarioSpace,
    settings: RoboProbeSettings,
    *,
    n: int,
    seed: int,
    repo_root: Path,
    workdir: Path,
) -> list[dict[str, Any]]:
    """Run ``n`` scrambled-Sobol scenarios through kinematic2d once each."""
    if n < 1:
        msg = "reference set size must be >= 1"
        raise ValueError(msg)
    rng = np.random.default_rng(seed)
    sampler = SobolSampler(space.dim)
    unit = sampler.sample(n, rng)
    task = load_task(repo_root / space.task_ref, strict=False, base_dir=repo_root)
    backend = Kinematic2DBackend(settings)
    engine = VerdictEngine(create_all(settings.oracles))
    sim, wall = episode_timeouts(settings.worker)
    rows: list[dict[str, Any]] = []
    for index, u in enumerate(unit):
        values = space.from_unit(u)
        scenario = _scenario(space, values)
        run_dir = workdir / f"ref-{index}"
        req = EpisodeRequest(
            run_id=uuid4(),
            scenario=scenario,
            task=task,
            sut_profile=SutProfile(
                id="k2d", backend="kinematic2d", config={}, config_hash="c" * 16
            ),
            seed=seed + index,
            workdir=run_dir,
            sim_time_budget_s=sim,
            wall_timeout_s=wall,
        )
        result = backend.run_episode(req, backend.materialize(req))
        outcome = engine.judge(result, task)
        rows.append(
            {
                "ordinal": index,
                "u0": float(u[0]),
                "u1": float(u[1]),
                "u2": float(u[2]),
                "u3": float(u[3]),
                "u4": float(u[4]),
                "u5": float(u[5]),
                "verdict": outcome.verdict.value,
                "robustness": outcome.robustness,
                "primary_failure": (
                    outcome.primary_failure.value if outcome.primary_failure else None
                ),
                "gt_label": None,
            }
        )
    return rows


def write_parquet(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """Write reference rows to ``path`` with schema version metadata."""
    table = pa.Table.from_pylist([dict(row) for row in rows])
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        table,
        path,
        compression="zstd",
        metadata={
            b"reference_schema_version": str(_REFERENCE_SCHEMA_VERSION).encode(),
        },
    )


def label_rows(
    rows: list[dict[str, Any]],
    calibration: K2DGtCalibration,
    *,
    radius: float,
) -> None:
    """Assign ``gt_label`` on failing rows via nearest calibrated canonical (MET-02)."""
    canonical = np.asarray([unit for _, unit in calibration.mode_points()], dtype=np.float64)
    labels = [name for name, _ in calibration.mode_points()]
    fail_idx = [i for i, row in enumerate(rows) if row["verdict"] == Verdict.FAIL.value]
    if not fail_idx:
        return
    fail_u = np.asarray([[rows[i][f"u{j}"] for j in range(6)] for i in fail_idx], dtype=np.float64)
    assigned = label_failures(fail_u, canonical, labels, radius=radius)
    for row_index, label in zip(fail_idx, assigned, strict=True):
        rows[row_index]["gt_label"] = None if label == NOVEL_LABEL else label


def write_manifest(path: Path, manifest: ReferenceManifest) -> None:
    """Persist manifest JSON next to the parquet artefact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.__dict__, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
