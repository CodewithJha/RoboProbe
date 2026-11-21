"""SUT profiles: strict loader and ``config_hash`` (docs/10 §4, docs/11 ``sut_profiles``).

A SUT profile names one robot-stack configuration so campaigns can compare stacks (UC-10, EXP-05):
kinematic2d controller constants or a Nav2 parameter set. Profiles are domain configuration
(docs/27 §1): they live in ``configs/sut_profiles/<id>.yaml`` and are never read from env vars.

Loading runs in stages, each reporting JSON pointers: strict YAML, JSON Schema
``schemas/sut_profile.schema.json`` (shape, including an unknown ``backend``), the typed per-backend
config model, then semantic checks (file name matches ``id``; ``provisional`` keys exist and are
rejected when ``strict``).

**Config hash.** ``config_hash = sha256(canonical_json({"backend": ..., "config": ...}))`` over the
*validated* config (defaults filled in), so comments, key order, ``name`` and ``description`` never
change it, while any value that changes robot behaviour does. Canonical JSON is the space-version
rule (docs/05 §3).

Implements: UC-10, EXP-05 (docs/03, docs/19)
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, cast

import pydantic
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from roboprobe.core.types import SutProfile
from roboprobe.scenario import hashing
from roboprobe.scenario._documents import (
    document_error,
    json_pointer,
    load_yaml_document,
    read_document,
    validate_document,
)

__all__ = [
    "PROFILE_CONFIGS",
    "GazeboNav2ProfileConfig",
    "Kinematic2DProfileConfig",
    "config_hash",
    "load_sut_profile",
    "load_sut_profile_text",
]

_SCHEMA = "sut_profile"
_CONFIG_POINTER = "/config"

NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
Scalar = float | int | bool | str


class _ProfileConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class Kinematic2DProfileConfig(_ProfileConfig):
    """kinematic2d stack: model file (T-029) plus per-profile constant overrides."""

    model_file: NonEmptyStr
    gain_overrides: dict[str, Scalar] = Field(default_factory=dict)


class GazeboNav2ProfileConfig(_ProfileConfig):
    """Nav2 stack: base parameter file, P1 speed keys and a nested parameter overlay."""

    base_nav2_params: NonEmptyStr
    speed_param_paths: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    nav2_overrides: dict[str, JsonValue] = Field(default_factory=dict)


PROFILE_CONFIGS: Mapping[str, type[_ProfileConfig]] = {
    "kinematic2d": Kinematic2DProfileConfig,
    "gazebo_nav2": GazeboNav2ProfileConfig,
}
"""Config model per supported backend; must match the schema's ``backend`` enum."""


def config_hash(backend: str, config: Mapping[str, JsonValue]) -> str:
    """Return the hex sha256 of the canonical JSON of ``backend`` and ``config``."""
    return hashing.content_hash({"backend": backend, "config": dict(config)})


def load_sut_profile(
    path: Path, *, strict: bool = False, max_bytes: int | None = None
) -> SutProfile:
    """Load, validate and hash a SUT profile file.

    Args:
        path: ``configs/sut_profiles/<id>.yaml``.
        strict: Also reject profiles with ``provisional`` values (release builds, Gazebo runs).
        max_bytes: Reject larger files (callers pass ``api.max_upload_mb`` for uploads).

    Returns:
        The profile with its normalised ``config`` and ``config_hash``.

    Raises:
        roboprobe.core.errors.NotFoundError: If the file does not exist.
        roboprobe.core.errors.ValidationError: On YAML, schema or model errors, an unknown backend,
            a file name that differs from ``id``, unknown ``provisional`` keys or (strict)
            provisional values; ``context["errors"]`` lists JSON pointers.
    """
    source = str(path)
    document = load_yaml_document(read_document(path), source=source, max_bytes=max_bytes)
    return _parse_document(
        document, source=source, strict=strict, expected_stem=path.stem, file_name=path.name
    )


def load_sut_profile_text(
    text: str | bytes,
    *,
    source: str,
    strict: bool = False,
    max_bytes: int | None = None,
) -> SutProfile:
    """Like :func:`load_sut_profile` for in-memory content (an API upload named ``source``).

    There is no file name to match, so the ``id`` check is skipped: the document is the source of
    truth for the profile id.
    """
    document = load_yaml_document(text, source=source, max_bytes=max_bytes)
    return _parse_document(document, source=source, strict=strict)


def _parse_document(
    document: object,
    *,
    source: str,
    strict: bool,
    expected_stem: str | None = None,
    file_name: str | None = None,
) -> SutProfile:
    validate_document(document, schema=_SCHEMA, source=source)
    document = cast("dict[str, Any]", document)  # the schema guarantees an object
    profile_id: str = document["id"]
    backend: str = document["backend"]
    model = PROFILE_CONFIGS.get(backend)
    if model is None:  # schema enum and PROFILE_CONFIGS drifted
        raise document_error(source, [("/backend", f"unsupported backend {backend!r}")])
    try:
        parsed = model.model_validate(document["config"])
    except pydantic.ValidationError as exc:
        raise document_error(
            source,
            [(_CONFIG_POINTER + json_pointer(e["loc"]), e["msg"]) for e in exc.errors()],
        ) from exc
    config: dict[str, JsonValue] = parsed.model_dump(mode="json")

    issues: list[tuple[str, str]] = []
    if expected_stem is not None and expected_stem != profile_id:
        issues.append(("/id", f"id {profile_id!r} must match the file name {file_name!r}"))
    provisional: list[str] = document.get("provisional", [])
    for index, key in enumerate(provisional):
        pointer = json_pointer(["provisional", index])
        if key not in config:
            issues.append((pointer, f"{key!r} is not a config key of backend {backend!r}"))
        elif strict:
            issues.append((pointer, f"config.{key} is provisional; not allowed in strict mode"))
    if issues:
        raise document_error(source, issues)

    return SutProfile(
        id=profile_id,
        backend=backend,
        config=config,
        config_hash=config_hash(backend, config),
    )
