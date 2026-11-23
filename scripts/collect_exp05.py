"""Collect one preregistered EXP-05 cell without running its post-collection analysis."""

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
    load_design,
    plan,
)
from roboprobe.experiments.runner import VARIANT_TAG_PREFIX, _as_campaign_row, export_raw_parquet
from roboprobe.runner.catalog import SutProfileService
from roboprobe.scenario._documents import read_document
from roboprobe.scenario.repo_root import discover_repo_root
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.sut_profile import load_sut_profile_text

_DESIGN_SHA256 = "ce40a7f73893dc10f1ae04c5af53f04bb4f31cc723d3f142c6692705db10b24a"
_PROFILES = {"profile_A": "tb4_nav2_default", "profile_B": "tb4_nav2_tuned"}


def _cell(
    design: ExperimentDesign,
    strategy: str,
    replicate: int,
    *,
    key: ComparabilityKey,
    default_seeds: int,
) -> CampaignSpec:
    matches = [
        spec
        for spec in plan(design, default_seeds=default_seeds, key=key)
        if (spec.strategy_label, spec.experiment_rep) == (strategy, replicate)
    ]
    if len(matches) != 1:
        msg = "requested cell is outside the registered EXP-05 plan"
        raise ValueError(msg)
    spec = matches[0]
    return spec.model_copy(update={"tags": (*spec.tags, f"{VARIANT_TAG_PREFIX}{strategy}")})


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Resolve the locked cell and export its proposal-ordered outcomes and provenance."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("strategy", choices=tuple(_PROFILES))
    parser.add_argument("replicate", type=int)
    parser.add_argument("output", type=Path)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args(argv)
    root = discover_repo_root()
    frozen = root / "configs/experiments/exp05_profiles.yaml"
    if hashlib.sha256(frozen.read_bytes()).hexdigest() != _DESIGN_SHA256:
        msg = "EXP-05 YAML differs from the preregistered bytes"
        raise ValueError(msg)
    design = load_design(frozen)
    space_path = root / "configs/scenario_spaces" / f"{design.space.id}.yaml"
    space = ScenarioSpace.from_yaml(space_path, base_dir=root)
    profile_path = root / "configs/sut_profiles" / f"{_PROFILES[args.strategy]}.yaml"
    profile_source = read_document(profile_path)
    profile = load_sut_profile_text(profile_source, source=str(profile_path))
    settings = load_settings()
    spec = _cell(
        design.model_copy(update={"sut_profile_id": profile.id}),
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
        print(f"EXP-05 cell {spec.name}: campaign {campaign_id}", flush=True)
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
                "risk_analysis": "pending",
            },
        )
        return 0 if complete else 1
    finally:
        services.close()


if __name__ == "__main__":
    raise SystemExit(main())
