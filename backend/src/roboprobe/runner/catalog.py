"""Catalogue services: scenario spaces and SUT profiles (docs/12 §2).

Layer: Application (L3). The HTTP routers and the CLI are thin adapters over these services; only
this module talks to a unit of work, so neither adapter imports ``roboprobe.store``
(docs/16 §2, import-linter ``adapters-wired-in-bootstrap``).

Implements: T-081a, FR-API-001, FR-SCN-001, UC-10
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, cast

from roboprobe.core.errors import ErrorCode, NotFoundError, ValidationError
from roboprobe.core.types import JsonValue
from roboprobe.runner.ports import (
    SpacePage,
    SpaceView,
    SutProfilePage,
    SutProfileView,
    UowFactory,
)
from roboprobe.scenario._documents import load_yaml_document
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.sut_profile import load_sut_profile_text

__all__ = [
    "REPO_ROOT",
    "NewSpace",
    "NewSutProfile",
    "Registration",
    "SpaceIssue",
    "SpaceService",
    "SpaceValidation",
    "SutProfileService",
    "discover_repo_root",
]

# catalog.py → runner → roboprobe → src → backend → repository root.
_SOURCE_LAYOUT_DEPTH: Final = 4
_UPLOAD_SOURCE: Final = "<upload>"


def discover_repo_root(start: Path | None = None) -> Path:
    """Directory that contains ``configs/scenario_spaces``.

    A source checkout is found by walking parents of this module. The backend image installs the
    package under ``site-packages`` and ships configs in the working directory (``/app``), so the
    walk continues from :func:`Path.cwd`.

    Args:
        start: File or directory to search from. Defaults to this module.

    Returns:
        The first directory on that walk that holds scenario-space YAML.

    Implements: T-047
    """
    origin = (start or Path(__file__)).resolve()
    cwd = Path.cwd().resolve()
    seen: set[Path] = set()
    for candidate in (origin, *origin.parents, cwd, *cwd.parents):
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / "configs" / "scenario_spaces").is_dir():
            return candidate
    if len(origin.parents) > _SOURCE_LAYOUT_DEPTH:
        return origin.parents[_SOURCE_LAYOUT_DEPTH]
    return origin


REPO_ROOT = discover_repo_root()
"""Repository root, or ``/app`` inside the backend image (T-047)."""


@dataclass(frozen=True, slots=True)
class NewSpace:
    """Fields required to persist one scenario-space version (structural ``SpaceRecord``)."""

    id: str
    version: str
    name: str
    definition: dict[str, JsonValue]
    schema_version: int = 1
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class NewSutProfile:
    """Fields required to persist one SUT profile (structural ``SutProfileRecord``)."""

    id: str
    backend: str
    config: dict[str, JsonValue]
    config_hash: str
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Registration[T]:
    """Result of an idempotent ``POST``: the stored item and whether this call created it."""

    item: T
    created: bool


@dataclass(frozen=True, slots=True)
class SpaceIssue:
    """One validation problem as an RFC 6901 pointer plus a message."""

    pointer: str
    message: str


@dataclass(frozen=True, slots=True)
class SpaceValidation:
    """Outcome of ``POST /spaces/validate`` (a query: invalid input is still a 200)."""

    valid: bool
    errors: tuple[SpaceIssue, ...] = ()
    dimension: int | None = None
    enabled_params: tuple[str, ...] = ()


class SpaceService:
    """Validate, register and list scenario spaces.

    Registration is content-addressed: ``ScenarioSpace.version`` is the hash of the canonical
    document (docs/05 §3), so re-posting identical content returns the stored version and any
    change creates a new ``(id, version)`` row.
    """

    def __init__(
        self,
        uow_factory: UowFactory,
        *,
        base_dir: Path | None = None,
        max_bytes: int | None = None,
    ) -> None:
        """Bind the service to a unit-of-work factory.

        Args:
            uow_factory: Opens one unit of work (context manager).
            base_dir: Directory a space's ``task`` reference is resolved against.
            max_bytes: Upload limit forwarded to the strict YAML loader.
        """
        self._uow_factory = uow_factory
        self._base_dir = base_dir
        self._max_bytes = max_bytes

    def list(self, *, limit: int | None = None, cursor: str | None = None) -> SpacePage:
        """Return one keyset page of registered spaces (id, version order)."""
        with self._uow_factory() as uow:
            return uow.spaces.list(limit=limit, cursor=cursor)

    def get(self, space_id: str, version: str) -> SpaceView:
        """Return one stored space version.

        Raises:
            roboprobe.core.errors.NotFoundError: If ``(space_id, version)`` is unknown.
        """
        with self._uow_factory() as uow:
            record = uow.spaces.get(space_id, version)
        if record is None:
            msg = f"space {space_id!r} version {version!r} not found"
            raise NotFoundError(msg, context={"space_id": space_id, "version": version})
        return record

    def register_bytes(
        self, raw: bytes, *, source: str = _UPLOAD_SOURCE
    ) -> Registration[SpaceView]:
        """Validate and store one space document (YAML or JSON bytes).

        Idempotent for identical canonical content: the second call returns the existing version
        with ``created=False``.

        Raises:
            roboprobe.core.errors.ValidationError: ``SPACE_INVALID`` with JSON-pointer errors.
        """
        document, space = self._parse(raw, source)
        record = NewSpace(
            id=space.id,
            version=space.version,
            name=space.name,
            definition=_json_mapping(document, source=source),
            schema_version=cast("int", document.get("schema_version", 1)),
        )
        with self._uow_factory() as uow:
            existing = uow.spaces.get(record.id, record.version)
            if existing is not None:
                return Registration(item=existing, created=False)
            uow.spaces.add(record)
            uow.commit()
        return Registration(item=record, created=True)

    def validate_bytes(self, raw: bytes, *, source: str = _UPLOAD_SOURCE) -> SpaceValidation:
        """Validate without storing; invalid input is reported, never raised."""
        try:
            _document, space = self._parse(raw, source)
        except ValidationError as exc:
            return SpaceValidation(valid=False, errors=_issues(exc))
        return SpaceValidation(
            valid=True,
            dimension=space.dim,
            enabled_params=tuple(param.id for param in space.params),
        )

    def _parse(self, raw: bytes, source: str) -> tuple[dict[str, JsonValue], ScenarioSpace]:
        document = load_yaml_document(
            raw, source=source, code=ErrorCode.SPACE_INVALID, max_bytes=self._max_bytes
        )
        space = ScenarioSpace.from_mapping(document, source=source, base_dir=self._base_dir)
        return _json_mapping(document, source=source), space


class SutProfileService:
    """Store and list SUT profiles (docs/10 §4, docs/11 ``sut_profiles``).

    Profiles are immutable by id: identical re-posts are idempotent, a different ``config_hash``
    for an existing id is rejected (silently replacing it would change running campaigns).
    """

    def __init__(self, uow_factory: UowFactory, *, max_bytes: int | None = None) -> None:
        """Bind the service to a unit-of-work factory.

        Args:
            uow_factory: Opens one unit of work (context manager).
            max_bytes: Upload limit forwarded to the strict YAML loader.
        """
        self._uow_factory = uow_factory
        self._max_bytes = max_bytes

    def list(self, *, limit: int | None = None, cursor: str | None = None) -> SutProfilePage:
        """Return one keyset page of registered profiles (id order)."""
        with self._uow_factory() as uow:
            return uow.sut_profiles.list(limit=limit, cursor=cursor)

    def create_bytes(
        self, raw: bytes, *, source: str = _UPLOAD_SOURCE
    ) -> Registration[SutProfileView]:
        """Validate and store one SUT profile (YAML or JSON bytes).

        Raises:
            roboprobe.core.errors.ValidationError: Invalid document, or an existing ``id`` with a
                different ``config_hash``.
        """
        profile = load_sut_profile_text(raw, source=source, max_bytes=self._max_bytes)
        record = NewSutProfile(
            id=profile.id,
            backend=profile.backend,
            config=dict(profile.config),
            config_hash=profile.config_hash,
        )
        with self._uow_factory() as uow:
            existing = uow.sut_profiles.get(record.id)
            if existing is not None:
                if existing.config_hash != record.config_hash:
                    msg = (
                        f"sut profile {record.id!r} already exists with a different config; "
                        "profiles are immutable - use a new id"
                    )
                    raise ValidationError(
                        msg,
                        context={
                            "profile_id": record.id,
                            "existing_hash": existing.config_hash,
                            "new_hash": record.config_hash,
                        },
                    )
                return Registration(item=existing, created=False)
            uow.sut_profiles.add(record)
            uow.commit()
        return Registration(item=record, created=True)


def _issues(exc: ValidationError) -> tuple[SpaceIssue, ...]:
    raw = exc.context.get("errors")
    issues: list[SpaceIssue] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, Mapping):
                issues.append(
                    SpaceIssue(
                        pointer=str(item.get("path", "")),
                        message=str(item.get("message", "")),
                    )
                )
    if not issues:
        issues.append(SpaceIssue(pointer="", message=exc.message))
    return tuple(issues)


def _json_mapping(document: object, *, source: str) -> dict[str, JsonValue]:
    if not isinstance(document, Mapping):
        msg = f"{source} must be a mapping"
        raise ValidationError(msg, code=ErrorCode.SPACE_INVALID, context={"source": source})
    return {str(key): _json_value(value) for key, value in document.items()}


def _json_value(value: object) -> JsonValue:
    """Normalise a ``yaml.safe_load`` value to the JSON type tree (no custom objects)."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    return str(value)
