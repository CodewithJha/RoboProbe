"""Collect disjoint seed slices from the frozen EXP-02 and EXP-07 designs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

from roboprobe.backends.kinematic2d.model import Kinematic2DModel
from roboprobe.bootstrap import build_cli_services
from roboprobe.bootstrap.experiments import SqlExperimentWriter
from roboprobe.cli.campaign import run_inline
from roboprobe.cli.experiment import _resolve_key
from roboprobe.cli.space import register_space
from roboprobe.core.clock import SystemClock
from roboprobe.core.settings import RoboProbeSettings, load_settings
from roboprobe.core.types import CampaignStatus
from roboprobe.experiments.planner import load_design, plan
from roboprobe.experiments.runner import ExperimentRunner
from roboprobe.runner.catalog import SutProfileService
from roboprobe.scenario._documents import read_document
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.sut_profile import load_sut_profile_text

REPO = Path(__file__).resolve().parents[1]
SHARDS = 5
WORKERS = 4
DESIGN_DIGESTS = {
    "exp02_analytic": "5f5c0b1625395096a4d066ce6d0bcfb447ee645ff52d2c6fc86a397cc5b47f6b",
    "exp02_branin": "8a33d0c2e6e17e7ae709d059ba3c234ea60b01ca4a92bc0b60ac347aa5b77ac3",
    "exp07_scalability": "fe36d7f77877982384d089b94b2490cc1b7da759ad58eefe56862f2c0428dba6",
    "exp07_scalability_d8": "da57986f777b3bc357e8c07556858e3950b5d50752a40e18ddf8bd2432779154",
    "exp07_scalability_noise2": "f06ec9280c64e310073bb844a8428c5fbfabd0ad622ee45de6a8b93e25c557d6",
}


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _settings() -> RoboProbeSettings:
    settings = load_settings()
    return settings.model_copy(
        update={
            "experiments": settings.experiments.model_copy(update={"max_concurrent_campaigns": 1})
        }
    )


def main() -> None:  # noqa: PLR0915 - keep the evidence and collection steps together
    """Load a frozen design, drive its assigned cells and export raw observations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", required=True, choices=DESIGN_DIGESTS)
    parser.add_argument("--shard", required=True, type=int, choices=range(SHARDS))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    arm: str = args.arm
    shard: int = args.shard

    path = REPO / "configs" / "experiments" / f"{arm}.yaml"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != DESIGN_DIGESTS[arm]:
        message = f"Frozen design hash mismatch for {arm}"
        raise ValueError(message)
    design = load_design(path)
    settings = _settings()
    space_path = REPO / "configs" / "scenario_spaces" / f"{design.space.id}.yaml"
    space = ScenarioSpace.from_yaml(space_path, base_dir=REPO)
    profile_path = REPO / "configs" / "sut_profiles" / f"{design.sut_profile_id}.yaml"
    source = str(profile_path)
    document = read_document(profile_path)
    profile = load_sut_profile_text(document, source=source)
    key = _resolve_key(space, profile.config_hash, design.backend)
    specs = plan(design, default_seeds=settings.experiments.default_seeds, key=key)
    selected = [spec for spec in specs if spec.experiment_rep % SHARDS == shard]
    reps = sorted({spec.experiment_rep for spec in selected})
    metrics = design.metrics if design.backend == "benchmark" else ("MET-03",)
    if not selected or len(selected) != len(reps) * len(design.strategies):
        message = f"Empty or incomplete design shard for {arm}"
        raise ValueError(message)
    benchmark = settings.selection.benchmarks
    if design.backend == "benchmark":
        function = "branin_falsify" if arm == "exp02_branin" else "multi_mode_6d"
        if not args.plan_only and benchmark.function != function:
            message = f"The benchmark runtime must use {function}"
            raise ValueError(message)
    model_version = None
    if design.backend == "kinematic2d":
        model_version = Kinematic2DModel.from_yaml(
            REPO / settings.backends.kinematic2d.model_file
        ).id

    manifest: dict[str, object] = {
        "arm": arm,
        "design_id": design.id,
        "shard": shard,
        "shard_count": SHARDS,
        "replicates": reps,
        "config_sha256": digest,
        "backend": design.backend,
        "space_id": space.id,
        "space_version": space.version,
        "k2d_model_version": model_version,
        "budget": design.budget,
        "space_definition_sha256": hashlib.sha256(space_path.read_bytes()).hexdigest(),
        "comparability": key.model_dump(mode="json"),
        "planned_design_cells": len(specs),
        "preregistered_metrics": list(design.metrics),
        "collected_metrics": list(metrics),
        "cells": [spec.model_dump(mode="json") for spec in selected],
        "workers": WORKERS,
        "campaigns_concurrent": settings.experiments.max_concurrent_campaigns,
        "benchmark_runtime": benchmark.model_dump(mode="json")
        if design.backend == "benchmark"
        else None,
        "git_commit": os.environ.get("GITHUB_SHA"),
        "runner_platform": platform.platform(),
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count(),
    }
    path_meta = out / "collection.json"
    _write_json(path_meta, manifest)
    print(
        f"{arm} shard {shard} selected {len(selected)}/{len(specs)} cells for reps {reps}",
        flush=True,
    )
    if args.plan_only:
        return

    register_space(space_path, settings, base_dir=REPO)
    services = build_cli_services(settings)
    writer = SqlExperimentWriter(services.make_uow)
    wall_start = monotonic()

    def drive(campaign_id: UUID) -> CampaignStatus:
        worker = settings.worker.model_copy(update={"id_prefix": f"t105a:{campaign_id.hex}"})
        local = settings.model_copy(update={"worker": worker})
        status = run_inline(campaign_id, local, workers=WORKERS, serve_probe=False)
        print(
            f"Campaign {campaign_id} ended {status} after {monotonic() - wall_start:.1f}s",
            flush=True,
        )
        if status is not CampaignStatus.COMPLETED:
            message = f"Campaign {campaign_id} did not complete: {status}"
            raise RuntimeError(message)
        return status

    rng_clock = SystemClock()
    try:
        SutProfileService(services.uow_factory).create_bytes(document, source=source)
        runner = ExperimentRunner(writer, settings.experiments, rng_clock, drive, new_uuid=uuid4)
        experiment_id = runner._create(design, selected)
        manifest["experiment_id"] = str(experiment_id)
        _write_json(path_meta, manifest)
        collection_design = design.model_copy(update={"metrics": metrics})
        raw_out = out / "runs.parquet"
        _, comparison = runner.start(
            collection_design, key, experiment_id=experiment_id, raw_parquet=raw_out
        )
        _write_json(out / "comparison.json", comparison)
        manifest["wall_seconds"] = monotonic() - wall_start
        manifest["raw_sha256"] = hashlib.sha256(raw_out.read_bytes()).hexdigest()
        _write_json(path_meta, manifest)
        _write_json(
            raw_out.with_suffix(".manifest.json"),
            {
                "sha256": manifest["raw_sha256"],
                "design_id": design.id,
                "config_sha256": digest,
                "backend": design.backend,
                "space_id": space.id,
                "space_version": space.version,
                "k2d_model_version": model_version,
                "budget": design.budget,
                "replicates": reps,
                "experiment_id": str(experiment_id),
            },
        )
    finally:
        services.close()


if __name__ == "__main__":
    main()
