"""``roboprobe export`` / ``roboprobe import`` campaign bundles (docs/05 §11).

Store adapters load via ``importlib`` (import-linter).

Implements: T-014, FR-STO-003
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType
from typing import Annotated, Literal
from uuid import UUID

import typer

from roboprobe.cli._context import get_state

__all__ = ["export_app", "import_app"]

export_app = typer.Typer(
    name="export",
    help="Export a campaign as a portable .tar.zst bundle.",
    invoke_without_command=True,
)
import_app = typer.Typer(
    name="import",
    help="Import a campaign bundle (.tar.zst).",
    invoke_without_command=True,
)


def _bundle_mod() -> ModuleType:
    return importlib.import_module("roboprobe.store.bundle")


def _artifacts_mod() -> ModuleType:
    return importlib.import_module("roboprobe.store.artifacts")


def _uow_mod() -> ModuleType:
    return importlib.import_module("roboprobe.store.uow")


def _engine_mod() -> ModuleType:
    return importlib.import_module("roboprobe.store.engine")


@export_app.callback(invoke_without_command=True)
def export_cmd(
    ctx: typer.Context,
    campaign_id: Annotated[UUID, typer.Argument(help="Campaign id to export.")],
    output: Annotated[Path, typer.Option("-o", "--output", help="Destination .tar.zst path.")],
) -> None:
    """Export ``campaign_id`` to ``output``."""
    if ctx.invoked_subcommand is not None:
        return
    state = get_state(ctx)
    settings = state.bootstrap()
    engine_mod = _engine_mod()
    engine = engine_mod.create_engine_from_settings(settings.database)
    factory = engine_mod.session_factory(engine)
    uow_cls = _uow_mod().SqlAlchemyUnitOfWork
    store = _artifacts_mod().LocalArtifactStore(settings.storage.artifact_root)
    try:
        with uow_cls(factory, notify_channel=settings.database.notify_channel) as uow:
            path = _bundle_mod().export_campaign(
                campaign_id,
                uow,
                store,
                output,
                settings=settings.storage.bundle,
            )
    finally:
        engine.dispose()
    state.output.data({"path": str(path), "campaign_id": str(campaign_id)})


@import_app.callback(invoke_without_command=True)
def import_cmd(
    ctx: typer.Context,
    bundle: Annotated[Path, typer.Argument(help="Path to a .tar.zst campaign bundle.")],
    on_conflict: Annotated[
        Literal["skip", "fail"],
        typer.Option("--on-conflict", help="Behaviour when the campaign id already exists."),
    ] = "fail",
) -> None:
    """Import ``bundle`` into the configured database and artefact store."""
    if ctx.invoked_subcommand is not None:
        return
    state = get_state(ctx)
    settings = state.bootstrap()
    engine_mod = _engine_mod()
    engine = engine_mod.create_engine_from_settings(settings.database)
    factory = engine_mod.session_factory(engine)
    uow_cls = _uow_mod().SqlAlchemyUnitOfWork
    store = _artifacts_mod().LocalArtifactStore(settings.storage.artifact_root)
    try:
        with uow_cls(factory, notify_channel=settings.database.notify_channel) as uow:
            campaign_id = _bundle_mod().import_bundle(
                bundle,
                uow,
                store,
                on_conflict=on_conflict,
                settings=settings.storage.bundle,
            )
    finally:
        engine.dispose()
    state.output.data({"campaign_id": str(campaign_id), "path": str(bundle)})
