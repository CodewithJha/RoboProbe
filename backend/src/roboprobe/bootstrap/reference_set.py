"""Dense kinematic2d reference set for MET-02/MET-08 (T-103, docs/19 §3).

Implements: FR-EXP-001, MET-02, MET-08
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from roboprobe.backends.base import EpisodeRequest, episode_timeouts
from roboprobe.backends.kinematic2d.backend import Kinematic2DBackend
from roboprobe.backends.kinematic2d.calibration import K2DGtCalibration, load_calibration
from roboprobe.backends.kinematic2d.model import Kinematic2DModel
from roboprobe.core import errors
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import Scenario, SutProfile, Verdict
from roboprobe.metrics.discovery_metrics import NOVEL_LABEL, label_failures
from roboprobe.oracles.registry import create_all
from roboprobe.oracles.verdict import EpisodeView, VerdictEngine
from roboprobe.scenario.hashing import scenario_hash
from roboprobe.scenario.samplers import SobolSampler
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.task import load_task

__all__ = [
    "ReferenceManifest",
    "generate_and_write",
    "generate_rows",
    "label_parquet",
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
    task = load_task(repo_root / space.task_ref, strict=False)
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
        outcome = engine.judge(cast(EpisodeView, result), task)
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
    meta = {b"reference_schema_version": str(_REFERENCE_SCHEMA_VERSION).encode()}
    pq.write_table(table.replace_schema_metadata(meta), path, compression="zstd")


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


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "configs" / "scenario_spaces").is_dir():
            return parent
    msg = "repository root not found (configs/scenario_spaces missing)"
    raise errors.ConfigError(msg)


def generate_and_write(
    settings: RoboProbeSettings,
    *,
    output: Path,
    n: int | None,
    seed: int | None,
    space_id: str,
) -> ReferenceManifest:
    """Generate, write parquet, and return manifest metadata."""
    ref = settings.experiments.reference_set
    count = n if n is not None else ref.n
    ref_seed = seed if seed is not None else ref.seed
    root = _repo_root()
    space = ScenarioSpace.from_yaml(
        root / "configs" / "scenario_spaces" / f"{space_id}.yaml", base_dir=root
    )
    work = Path(settings.storage.workdir_root) / "reference-generate"
    rows = generate_rows(space, settings, n=count, seed=ref_seed, repo_root=root, workdir=work)
    write_parquet(output, rows)
    model = Kinematic2DModel.from_yaml(Path(settings.backends.kinematic2d.model_file))
    manifest = ReferenceManifest(
        path=str(output),
        sha256=sha256_file(output),
        n=count,
        seed=ref_seed,
        space_id=space.id,
        space_version=space.version,
        k2d_model_version=model.id,
    )
    write_manifest(output.with_suffix(".manifest.json"), manifest)
    return manifest


def label_parquet(
    settings: RoboProbeSettings,
    source: Path,
    *,
    output: Path | None,
) -> tuple[Path, int]:
    """Label failures in ``source`` and write to ``output`` (default in-place)."""
    calibration = load_calibration(Path(settings.backends.kinematic2d.calibration_file))
    table = pq.read_table(source)
    rows = table.to_pylist()
    label_rows(rows, calibration, radius=settings.experiments.mode_match_radius)
    dest = output or source
    write_parquet(dest, rows)
    return dest, sum(1 for row in rows if row.get("gt_label"))
