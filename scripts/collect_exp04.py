"""Collect one preregistered EXP-04 cell without running its post-collection analysis."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from roboprobe.bootstrap import build_cli_services
from roboprobe.bootstrap.experiments import SqlExperimentWriter
from roboprobe.cli.campaign import run_inline
from roboprobe.cli.experiment import _resolve_key
from roboprobe.cli.space import register_space
from roboprobe.core.settings import load_settings
from roboprobe.core.types import CampaignStatus
from roboprobe.experiments.planner import (
    CampaignSpec,
    ComparabilityKey,
    ExperimentDesign,
    StrategyVariant,
    load_design,
    plan,
)
from roboprobe.experiments.runner import _as_campaign_row, export_raw_parquet
from roboprobe.runner.catalog import SutProfileService
from roboprobe.scenario._documents import read_document
from roboprobe.scenario.repo_root import discover_repo_root
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.sut_profile import load_sut_profile_text

_DESIGN_SHA256 = "1e5b74000d42ae4b2be121d5d94aec31e55c97c915e1733e110f07129fb34d7a"
_OFAT_BUDGET = 30
_OFAT = "S-OFAT"


def _cell(
    design: ExperimentDesign,
    strategy: str,
    replicate: int,
    *,
    key: ComparabilityKey,
    default_seeds: int,
) -> CampaignSpec:
    if strategy == _OFAT:
        design = design.model_copy(
            update={
                "strategies": (StrategyVariant(id=_OFAT),),
                "seeds": design.seeds.model_copy(update={"count": 1}),
                "budget": _OFAT_BUDGET,
            }
        )
    matches = [
        spec
        for spec in plan(design, default_seeds=default_seeds, key=key)
        if (spec.strategy_id, spec.experiment_rep) == (strategy, replicate)
    ]
    if len(matches) != 1:
        msg = "requested cell is outside the registered EXP-04 plan"
        raise ValueError(msg)
    return matches[0]


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Resolve the locked cell and export its proposal-ordered outcomes and provenance."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("strategy", choices=("S-RANDOM", "S-PROBE", _OFAT))
    parser.add_argument("replicate", type=int)
    parser.add_argument("output", type=Path)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args(argv)
    root = discover_repo_root()
    frozen = root / "configs/experiments/exp04_gazebo.yaml"
    if hashlib.sha256(frozen.read_bytes()).hexdigest() != _DESIGN_SHA256:
        msg = "EXP-04 YAML differs from the preregistered bytes"
        raise ValueError(msg)
    design = load_design(frozen)
    space_path = root / "configs/scenario_spaces" / f"{design.space.id}.yaml"
    space = ScenarioSpace.from_yaml(space_path, base_dir=root)
    profile_path = root / "configs/sut_profiles" / f"{design.sut_profile_id}.yaml"
    profile_source = read_document(profile_path)
    profile = load_sut_profile_text(profile_source, source=str(profile_path))
    settings = load_settings()
    spec = _cell(
        design,
        args.strategy,
        args.replicate,
        key=_resolve_key(space, profile.config_hash, design.backend),
        default_seeds=settings.experiments.default_seeds,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    provenance = {
        "config_sha256": _DESIGN_SHA256,
        "design": design.model_dump(mode="json"),
        "cell": spec.model_dump(mode="json"),
        "profile_sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        "ofat_note": "Separate doc 19 cell, first registered CRN seed"
        if spec.strategy_id == _OFAT
        else None,
    }
    _write_json(args.output / "registered-cell.json", provenance)
    if args.plan_only:
        return 0

    register_space(space_path, settings, base_dir=root)
    services = build_cli_services(settings)
    writer = SqlExperimentWriter(services.make_uow)
    try:
        SutProfileService(services.uow_factory).create_bytes(
            profile_source, source=str(profile_path)
        )
        experiment_id = writer.add_experiment(
            name=spec.name,
            design={
                **design.model_dump(mode="json"),
                "collection_cell": spec.model_dump(mode="json"),
            },
            status="RUNNING",
        )
        campaign_id = writer.add_campaign(spec, experiment_id)
        print(f"EXP-04 cell {spec.name}: campaign {campaign_id}", flush=True)
        status = run_inline(campaign_id, settings, workers=1, serve_probe=False)
        with services.make_uow() as uow:
            campaign = uow.campaigns.get(campaign_id)
        if campaign is None:
            msg = "collected campaign is missing"
            raise RuntimeError(msg)
        observed = writer.campaign_runs(campaign_id)
        raw = args.output / "runs.parquet"
        export_raw_parquet(raw, [_as_campaign_row(campaign)], {campaign_id: observed})
        complete = status is CampaignStatus.COMPLETED and len(observed) == spec.budget
        writer.set_experiment_status(experiment_id, "COMPLETED" if complete else "FAILED")
        _write_json(
            args.output / "collection.json",
            {
                **provenance,
                "experiment_id": str(experiment_id),
                "campaign_id": str(campaign_id),
                "campaign_status": status.value,
                "observed_episodes": len(observed),
                "expected_episodes": spec.budget,
                "raw_parquet_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
                "pooled_analysis": "pending",
            },
        )
        return 0 if complete else 1
    finally:
        services.close()


if __name__ == "__main__":
    raise SystemExit(main())
