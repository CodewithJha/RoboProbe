"""``roboprobe gc`` and ``roboprobe artifacts verify`` (docs/05 §11).

Store adapters are loaded via ``importlib`` so this module stays import-linter clean
(bootstrap wiring, T-046).

Implements: T-013b
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Annotated

import typer

from roboprobe.cli._context import get_state
from roboprobe.core.clock import SystemClock

__all__ = ["app", "gc_app"]

app = typer.Typer(name="artifacts", help="Verify artefact store integrity.", no_args_is_help=True)
gc_app = typer.Typer(name="gc", help="Delete orphaned artefacts.", invoke_without_command=True)


def _store_mod() -> ModuleType:
    return importlib.import_module("roboprobe.store.maintenance")


def _artifacts_mod() -> ModuleType:
    return importlib.import_module("roboprobe.store.artifacts")


def _uow_mod() -> ModuleType:
    return importlib.import_module("roboprobe.store.uow")


def _engine_mod() -> ModuleType:
    return importlib.import_module("roboprobe.store.engine")


@gc_app.callback()
def gc_cmd(
    ctx: typer.Context,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="List deletions without removing files.")
    ] = False,
) -> None:
    """Garbage-collect unreferenced blobs and apply bag retention."""
    if ctx.invoked_subcommand is not None:
        return
    state = get_state(ctx)
    settings = state.bootstrap()
    engine_mod = _engine_mod()
    engine = engine_mod.create_engine_from_settings(settings.database)
    factory = engine_mod.session_factory(engine)
    uow_cls = _uow_mod().SqlAlchemyUnitOfWork
    store = _artifacts_mod().LocalArtifactStore(settings.storage.artifact_root)
    report = _store_mod().gc(
        lambda: uow_cls(factory, notify_channel=settings.database.notify_channel),
        store,
        settings.storage.retention,
        now=SystemClock().now(),
        grace_s=settings.runner.heartbeat_timeout_s,
        dry_run=dry_run,
    )
    engine.dispose()
    state.output.data(
        {
            "dry_run": report.dry_run,
            "orphans": [str(p) for p in report.orphans],
            "bags_deleted": [str(i) for i in report.retained_bags_deleted],
        }
    )


@app.command("verify")
def verify_cmd(ctx: typer.Context) -> None:
    """Re-hash blobs and report mismatches."""
    state = get_state(ctx)
    settings = state.bootstrap()
    store = _artifacts_mod().LocalArtifactStore(settings.storage.artifact_root)
    mismatches = _store_mod().verify(store)
    state.output.data(
        {
            "ok": not mismatches,
            "mismatches": [
                {"path": str(item.path), "expected": item.expected, "actual": item.actual}
                for item in mismatches
            ],
        }
    )
