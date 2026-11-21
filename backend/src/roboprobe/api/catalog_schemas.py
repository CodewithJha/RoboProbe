"""DTOs for the scenario-space and SUT-profile routers (docs/12 §2).

Layer: Interface (L4).

Implements: T-081a, FR-API-001
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from roboprobe.core.types import JsonValue
from roboprobe.runner.catalog import SpaceValidation
from roboprobe.runner.ports import SpaceView, SutProfileView

__all__ = [
    "SpaceError",
    "SpaceSummary",
    "SpaceValidationResult",
    "SpaceVersion",
    "SutProfileDTO",
    "space_summary",
    "space_validation",
    "space_version",
    "sut_profile_dto",
]


class SpaceError(BaseModel):
    """One validation problem: RFC 6901 pointer plus a message."""

    model_config = ConfigDict(extra="forbid")

    pointer: str
    message: str


class SpaceSummary(BaseModel):
    """List-row view of one registered space version."""

    model_config = ConfigDict(extra="forbid")

    id: str
    version: str
    name: str
    description: str = ""
    dimension: int
    enabled_params: list[str]
    schema_version: int
    created_at: datetime | None = None


class SpaceVersion(BaseModel):
    """Full stored definition of one space version (docs/12 §6)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    version: str
    name: str
    description: str = ""
    definition: dict[str, JsonValue]
    schema_version: int
    created_at: datetime | None = None


class SpaceValidationResult(BaseModel):
    """Outcome of ``POST /spaces/validate`` (HTTP 200 even when invalid)."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[SpaceError] = []
    dimension: int | None = None
    enabled_params: list[str] = []


class SutProfileDTO(BaseModel):
    """One robot-stack profile (docs/11 ``sut_profiles``)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    backend: str
    config: dict[str, JsonValue]
    config_hash: str
    created_at: datetime | None = None


def space_summary(space: SpaceView) -> SpaceSummary:
    """Project a stored space record onto its list representation."""
    enabled = _enabled_parameters(space.definition)
    return SpaceSummary(
        id=space.id,
        version=space.version,
        name=space.name,
        description=_description(space.definition),
        dimension=len(enabled),
        enabled_params=enabled,
        schema_version=space.schema_version,
        created_at=space.created_at,
    )


def space_version(space: SpaceView) -> SpaceVersion:
    """Project a stored space record onto its full representation."""
    return SpaceVersion(
        id=space.id,
        version=space.version,
        name=space.name,
        description=_description(space.definition),
        definition=space.definition,
        schema_version=space.schema_version,
        created_at=space.created_at,
    )


def space_validation(result: SpaceValidation) -> SpaceValidationResult:
    """Project the service's validation outcome onto its HTTP representation."""
    return SpaceValidationResult(
        valid=result.valid,
        errors=[
            SpaceError(pointer=issue.pointer, message=issue.message) for issue in result.errors
        ],
        dimension=result.dimension,
        enabled_params=list(result.enabled_params),
    )


def sut_profile_dto(profile: SutProfileView) -> SutProfileDTO:
    """Project a stored SUT profile onto its HTTP representation."""
    return SutProfileDTO(
        id=profile.id,
        backend=profile.backend,
        config=profile.config,
        config_hash=profile.config_hash,
        created_at=profile.created_at,
    )


def _description(definition: Mapping[str, JsonValue]) -> str:
    value = definition.get("description")
    return value if isinstance(value, str) else ""


def _enabled_parameters(definition: Mapping[str, JsonValue]) -> list[str]:
    """Ids of the enabled parameters in file order (dimension without pins)."""
    raw = definition.get("parameters")
    if not isinstance(raw, list):
        return []
    ids: list[str] = []
    for item in raw:
        if (
            isinstance(item, Mapping)
            and item.get("enabled", True)
            and isinstance(item.get("id"), str)
        ):
            ids.append(str(item["id"]))
    return ids
