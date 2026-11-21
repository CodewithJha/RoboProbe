"""Create campaigns from API payloads (docs/12 §3.1).

Implements: T-081, FR-API-001
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
import yaml

from roboprobe.api._store import new_uuid, records
from roboprobe.api.schemas import CampaignCreate
from roboprobe.bootstrap.campaigns import campaign_supported_params
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.core.seeding import random_campaign_seed
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import CampaignStatus, JsonValue
from roboprobe.runner.campaign_factory import CampaignFactory
from roboprobe.runner.lifecycle import CampaignService
from roboprobe.scenario._documents import load_yaml_document, read_document, validate_document
from roboprobe.scenario.repo_root import discover_repo_root
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.sut_profile import load_sut_profile
from roboprobe.selection.base import StrategyContext
from roboprobe.selection.registry import create as create_strategy

__all__ = ["create_campaign"]


def create_campaign(
    body: CampaignCreate,
    *,
    uow: Any,
    settings: RoboProbeSettings,
    campaigns: CampaignService,
    space_root: Path | None = None,
) -> UUID:
    """Validate and insert a campaign; optionally start it."""
    root = discover_repo_root() if space_root is None else space_root
    if body.budget > settings.runner.max_budget:
        msg = f"budget {body.budget} exceeds runner.max_budget {settings.runner.max_budget}"
        raise ValidationError(msg, context={"budget": body.budget})
    if body.batch_size < 1 or body.batch_size > settings.runner.max_batch_size:
        msg = f"batch_size must be in 1..{settings.runner.max_batch_size}"
        raise ValidationError(msg, context={"batch_size": body.batch_size})
    space_id = body.space.id
    existing = uow.spaces.get(space_id, body.space.version) if body.space.version else None
    if existing is not None:
        space = ScenarioSpace.from_text(
            yaml.safe_dump(existing.definition), source="registered space", base_dir=root
        )
    else:
        space_yaml = _config_path(root, "scenario_spaces", space_id)
        if not space_yaml.is_file():
            msg = f"scenario space not found for {space_id!r}"
            raise NotFoundError(msg, context={"space_id": space_id})
        space = ScenarioSpace.from_yaml(space_yaml, base_dir=root)
        if body.space.version is not None and body.space.version != space.version:
            msg = "registered space version not found"
            raise NotFoundError(msg, context={"space_id": space_id})
        _ensure_space_row(uow, space, space_yaml)
    body = CampaignFactory(settings).prepare(
        body, space=space, supported_params=campaign_supported_params(body.backend, settings)
    )
    backend = body.backend
    default_sut = "k2d_default" if backend == "kinematic2d" else ""
    profile_id = body.sut_profile_id or default_sut
    if not profile_id:
        msg = "sut_profile_id is required"
        raise ValidationError(msg)
    _ensure_sut(uow, profile_id, backend, root)
    seed = (
        body.strategy.seed
        if body.strategy.seed is not None
        else random_campaign_seed(np.random.default_rng())
    )
    strategy_id = body.strategy.id
    ctx = StrategyContext(
        space=space,
        budget=body.budget,
        seed=seed,
        batch_size=body.batch_size,
        params=dict(body.strategy.params),
    )
    create_strategy(strategy_id, ctx)
    cid = new_uuid()
    name = body.name or f"{space_id}-{strategy_id}"
    rec = records()
    uow.campaigns.add(
        rec.CampaignRecord(
            id=cid,
            name=name,
            space_id=space.id,
            space_version=space.version,
            sut_profile_id=profile_id,
            backend=backend,
            strategy_id=strategy_id,
            strategy_params=dict(body.strategy.params),
            seed=seed,
            budget=body.budget,
            repeats=body.repeats,
            batch_size=body.batch_size,
            pins=dict(body.pins),
            oracle_config=dict(body.oracle_overrides),
            stop_rules=dict(body.stop_rules),
            status=CampaignStatus.CREATED,
            tags=tuple(body.tags),
        )
    )
    if body.start:
        # Lifecycle uses a separate transaction and must see the inserted campaign.
        uow.commit()
        campaigns.start(cid)
    return UUID(str(cid))


def _ensure_space_row(uow: Any, space: ScenarioSpace, path: Path) -> None:
    existing = uow.spaces.get(space.id, space.version)
    if existing is not None:
        return
    document = load_yaml_document(read_document(path), source=str(path))
    if not isinstance(document, dict):
        msg = "space document must be a mapping"
        raise ValidationError(msg)
    definition = {str(k): _as_json(v) for k, v in document.items()}
    rec = records()
    uow.spaces.add(
        rec.SpaceRecord(
            id=space.id,
            version=space.version,
            name=space.name,
            definition=definition,
            schema_version=int(str(document.get("schema_version", 1))),
        )
    )


def _ensure_sut(uow: Any, profile_id: str, backend: str, root: Path) -> None:
    registered = uow.sut_profiles.get(profile_id)
    if registered is not None and hasattr(registered, "backend"):
        if registered.backend != backend:
            msg = "SUT profile backend does not match campaign backend"
            raise ValidationError(msg)
        return
    path = _config_path(root, "sut_profiles", profile_id)
    if not path.is_file():
        msg = f"SUT profile file not found: {path}"
        raise NotFoundError(msg, context={"sut_profile_id": profile_id})
    profile = load_sut_profile(path, strict=False)
    if profile.backend != backend:
        msg = f"SUT profile backend {profile.backend!r} != campaign backend {backend!r}"
        raise ValidationError(msg, context={"sut_profile_id": profile_id})
    if uow.sut_profiles.get(profile.id) is None:
        rec = records()
        uow.sut_profiles.add(
            rec.SutProfileRecord(
                id=profile.id,
                backend=profile.backend,
                config=dict(profile.config),
                config_hash=profile.config_hash,
            )
        )


def _as_json(value: object) -> JsonValue:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _as_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_as_json(v) for v in value]
    return str(value)


def parse_space_body(raw: bytes, content_type: str) -> dict[str, JsonValue]:
    """Parse YAML or JSON space payload."""
    if "yaml" in content_type:
        parsed = yaml.safe_load(raw.decode("utf-8"))
    else:
        import json

        parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        msg = "space body must be an object"
        raise ValidationError(msg)
    import json

    document = load_yaml_document(json.dumps(parsed), source="api")
    validate_document(document, schema="scenario_space", source="api")
    return {str(k): _as_json(v) for k, v in parsed.items()}


def _config_path(root: Path, kind: str, identifier: str) -> Path:
    directory = (root / "configs" / kind).resolve()
    path = (directory / f"{identifier}.yaml").resolve()
    if not path.is_relative_to(directory):
        msg = "configuration reference escapes its directory"
        raise ValidationError(msg)
    return path
