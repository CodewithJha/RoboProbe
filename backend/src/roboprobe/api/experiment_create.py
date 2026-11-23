"""Plan and stage opt-in experiment campaign matrices (T-084a)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from roboprobe import __version__
from roboprobe.api.campaign_create import _ensure_sut, create_campaign, resolve_campaign_space
from roboprobe.api.deps import ServicesProto
from roboprobe.api.schemas import CampaignCreate, SpaceRef, StrategyRef
from roboprobe.core.errors import ValidationError
from roboprobe.core.types import JsonValue
from roboprobe.experiments.planner import (
    CampaignSpec,
    ComparabilityKey,
    ExperimentDesign,
    plan,
    sut_profile_ids,
)
from roboprobe.experiments.runner import VARIANT_TAG_PREFIX
from roboprobe.oracles import __version__ as oracle_set_version
from roboprobe.scenario._documents import validate_document

__all__ = ["plan_experiment", "stage_campaigns"]


def plan_experiment(
    design: ExperimentDesign,
    document: dict[str, JsonValue],
    *,
    uow: Any,
    services: ServicesProto,
) -> tuple[ComparabilityKey, list[CampaignSpec]]:
    """Resolve shared inputs and enforce the API's cell limit before expanding the matrix."""
    validate_document(document, schema="experiment", source="api")
    settings = services.settings
    count = design.seeds.count or settings.experiments.default_seeds
    cells = len(design.strategies) * count
    if cells > settings.api.experiment_max_cells:
        msg = "experiment exceeds the configured cell limit"
        raise ValidationError(
            msg, context={"cells": cells, "limit": settings.api.experiment_max_cells}
        )

    ref = SpaceRef(id=design.space.id, version=design.space.version)
    space = resolve_campaign_space(ref, uow=uow, root=services.space_root)
    profile_id = design.sut_profile_id or ("k2d_default" if design.backend == "kinematic2d" else "")
    if not profile_id:
        msg = "sut_profile_id is required for this experiment backend"
        raise ValidationError(msg)
    for pid in sorted(sut_profile_ids(design)):
        _ensure_sut(uow, pid, design.backend, services.space_root)
    profile = uow.sut_profiles.get(profile_id)
    key = ComparabilityKey(
        space_version=space.version,
        oracle_set_version=oracle_set_version,
        sut_config_hash=profile.config_hash,
        backend_version=__version__,
        k2d_model_version="kinematic2d" if design.backend == "kinematic2d" else "n/a",
    )
    return key, plan(design, default_seeds=settings.experiments.default_seeds, key=key)


def stage_campaigns(
    experiment_id: UUID,
    specs: list[CampaignSpec],
    *,
    uow: Any,
    services: ServicesProto,
) -> None:
    """Validate and record every campaign inside the experiment creation transaction."""
    for spec in specs:
        create_campaign(
            CampaignCreate(
                name=spec.name,
                space=SpaceRef(id=spec.space_id, version=spec.space_version),
                sut_profile_id=spec.sut_profile_id,
                backend=spec.backend,
                strategy=StrategyRef(
                    id=spec.strategy_id, seed=spec.seed, params=spec.strategy_params
                ),
                budget=spec.budget,
                repeats=spec.repeats,
                batch_size=spec.batch_size,
                pins=spec.pins,
                oracle_overrides=spec.oracle_overrides,
                stop_rules=spec.stop_rules,
                tags=(f"{VARIANT_TAG_PREFIX}{spec.strategy_label}", *spec.tags),
            ),
            uow=uow,
            settings=services.settings,
            campaigns=services.campaigns,
            space_root=services.space_root,
            experiment_cell=(experiment_id, spec.experiment_rep),
        )
