"""``roboprobe space``: validate, register, list and upgrade scenario spaces.

Layer: Interface (L4).

Implements: T-045a, FR-CLI-001, FR-SCN-001
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import yaml

from roboprobe.bootstrap import build_cli_services
from roboprobe.cli._context import get_state
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.runner.catalog import REPO_ROOT, SpaceService, discover_repo_root
from roboprobe.runner.ports import SpaceView
from roboprobe.scenario._documents import load_yaml_document, read_document
from roboprobe.scenario.space import ScenarioSpace

__all__ = ["REPO_ROOT", "app", "discover_repo_root", "register_space"]

app = typer.Typer(
    name="space",
    help="Scenario space validate / register / list.",
    no_args_is_help=True,
)


def register_space(
    path: Path,
    settings: RoboProbeSettings,
    *,
    base_dir: Path | None = None,
) -> SpaceView:
    """Validate ``path`` and persist the space definition + version (idempotent)."""
    root = REPO_ROOT if base_dir is None else base_dir
    raw = read_document(path)
    services = build_cli_services(settings)
    try:
        service = SpaceService(services.uow_factory, base_dir=root)
        return service.register_bytes(raw, source=str(path)).item
    finally:
        services.close()


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
        page = SpaceService(services.uow_factory, base_dir=REPO_ROOT).list()
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
