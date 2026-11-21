"""``roboprobe space``: validate, register, list and upgrade scenario spaces.

Layer: Interface (L4).

Implements: T-045a, FR-CLI-001, FR-SCN-001
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Annotated, Protocol, cast

import typer
import yaml

from roboprobe.bootstrap import build_cli_services
from roboprobe.cli._context import get_state
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import JsonValue
from roboprobe.scenario._documents import load_yaml_document, read_document
from roboprobe.scenario.space import ScenarioSpace

__all__ = ["REPO_ROOT", "app", "discover_repo_root", "register_space"]

# cli/space.py → cli → roboprobe → src → backend → repository root.
_SOURCE_LAYOUT_DEPTH = 4

app = typer.Typer(
    name="space",
    help="Scenario space validate / register / list.",
    no_args_is_help=True,
)


def discover_repo_root(start: Path | None = None) -> Path:
    """Directory that contains ``configs/scenario_spaces``.

    A source checkout is found by walking parents of this module. The backend
    image installs the package under ``site-packages`` and ships configs in the
    working directory (``/app``), so the walk continues from :func:`Path.cwd`.

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


class _SpaceRow(Protocol):
    id: str
    version: str
    name: str


def register_space(
    path: Path,
    settings: RoboProbeSettings,
    *,
    base_dir: Path | None = None,
) -> _SpaceRow:
    """Validate ``path`` and persist the space definition + version."""
    root = REPO_ROOT if base_dir is None else base_dir
    space = ScenarioSpace.from_yaml(path, base_dir=root)
    document = load_yaml_document(read_document(path), source=str(path))
    if not isinstance(document, dict):
        msg = "space document must be a mapping"
        raise ValidationError(msg, context={"path": str(path)})
    definition = {str(key): _as_json(value) for key, value in document.items()}
    records = importlib.import_module("roboprobe.store.records")
    record = records.SpaceRecord(
        id=space.id,
        version=space.version,
        name=space.name,
        definition=definition,
        schema_version=int(document.get("schema_version", 1)),
    )
    services = build_cli_services(settings)
    try:
        with services.make_uow() as uow:
            existing = uow.spaces.get(record.id, record.version)
            if existing is None:
                uow.spaces.add(record)
            uow.commit()
    finally:
        services.close()
    return cast("_SpaceRow", record)


def _as_json(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list):
        return [_as_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _as_json(item) for key, item in value.items()}
    return str(value)


@app.command("validate")
def validate_cmd(
    ctx: typer.Context,
    yaml_path: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, help="Space YAML file."),
    ],
) -> None:
    """Validate a scenario space file (exit 0 / 2 with path-to-error messages)."""
    state = get_state(ctx)
    state.bootstrap()
    space = ScenarioSpace.from_yaml(yaml_path, base_dir=REPO_ROOT)
    state.output.data({"id": space.id, "version": space.version, "name": space.name})


@app.command("register")
def register_cmd(
    ctx: typer.Context,
    yaml_path: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, help="Space YAML file."),
    ],
) -> None:
    """Validate and store a space definition + version in the database."""
    state = get_state(ctx)
    settings = state.bootstrap()
    record = register_space(yaml_path, settings, base_dir=REPO_ROOT)
    state.output.data({"id": record.id, "version": record.version, "name": record.name})


@app.command("list")
def list_cmd(ctx: typer.Context) -> None:
    """List registered scenario spaces."""
    state = get_state(ctx)
    settings = state.bootstrap()
    services = build_cli_services(settings)
    try:
        with services.make_uow() as uow:
            page = uow.spaces.list()
            rows = [[item.id, item.version, item.name] for item in page.items]
    finally:
        services.close()
    state.output.table(["id", "version", "name"], rows, title="Scenario spaces")


@app.command("upgrade")
def upgrade_cmd(
    ctx: typer.Context,
    yaml_path: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, help="Space YAML file."),
    ],
) -> None:
    """Migrate a space file to the current ``schema_version`` (stub until schema v2).

    Docs/05 §11 and docs/33: future schema versions will rewrite the YAML in place.
    """
    state = get_state(ctx)
    state.bootstrap()
    document = load_yaml_document(read_document(yaml_path), source=str(yaml_path))
    if not isinstance(document, dict):
        msg = "space document must be a mapping"
        raise ValidationError(msg, context={"path": str(yaml_path)})
    version = document.get("schema_version")
    if version != 1:
        msg = (
            f"space upgrade cannot migrate schema_version={version!r}; "
            "only schema_version=1 is supported (no rewrite needed)"
        )
        raise NotFoundError(msg, context={"path": str(yaml_path), "schema_version": version})
    yaml_path.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    state.output.data({"path": str(yaml_path), "schema_version": 1, "upgraded": False})
