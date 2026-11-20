"""``roboprobe db``: database migrations via the Alembic Python API (no subprocess).

Layer: Interface (L4).

Implements: T-045a, FR-CLI-001
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType

import typer
from alembic import command
from alembic.config import Config

from roboprobe.cli._context import get_state
from roboprobe.core.settings import RoboProbeSettings

__all__ = ["app", "upgrade_head"]

app = typer.Typer(name="db", help="Database migrations.", no_args_is_help=True)

_BACKEND_ROOT = Path(__file__).resolve().parents[3]
"""``backend/`` directory (``cli/db.py`` → ``roboprobe`` → ``src`` → ``backend``)."""


def _engine_mod() -> ModuleType:
    return importlib.import_module("roboprobe.store.engine")


def _alembic_config() -> Config:
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    cfg.set_main_option("prepend_sys_path", str(_BACKEND_ROOT / "src"))
    return cfg


def upgrade_head(settings: RoboProbeSettings) -> None:
    """Run Alembic ``upgrade head`` using ``settings.database`` (docs/05 §11)."""
    engine_mod = _engine_mod()
    engine = engine_mod.create_engine_from_settings(settings.database)
    cfg = _alembic_config()
    try:
        with engine.connect() as connection:
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "head")
            connection.commit()
    finally:
        engine.dispose()


@app.command("upgrade")
def upgrade_cmd(ctx: typer.Context) -> None:
    """Apply all pending migrations (Alembic upgrade head)."""
    state = get_state(ctx)
    settings = state.bootstrap()
    upgrade_head(settings)
    state.output.data({"status": "ok", "revision": "head"})
