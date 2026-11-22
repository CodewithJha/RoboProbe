"""Alembic up/down/up and empty autogenerate diff (T-010b)."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import produce_migrations
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

from roboprobe.store.orm import Base

pytestmark = pytest.mark.integration

BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _alembic_cfg() -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.set_main_option("prepend_sys_path", str(BACKEND_ROOT / "src"))
    return cfg


def test_upgrade_downgrade_upgrade(pg_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "ROBOPROBE_DATABASE__URL",
        pg_engine.url.render_as_string(hide_password=False),
    )
    cfg = _alembic_cfg()
    with pg_engine.begin() as conn:
        Base.metadata.drop_all(conn)
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    with pg_engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
        conn.commit()
    inspector = inspect(pg_engine)
    assert "runs" in inspector.get_table_names()
    script = ScriptDirectory.from_config(cfg)
    assert script.get_current_head() == "0003_mode_duplicates"


def test_autogenerate_is_empty(pg_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "ROBOPROBE_DATABASE__URL",
        pg_engine.url.render_as_string(hide_password=False),
    )
    cfg = _alembic_cfg()
    with pg_engine.begin() as conn:
        Base.metadata.drop_all(conn)
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    with pg_engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        conn.commit()
        context = MigrationContext.configure(
            conn, opts={"compare_type": True, "target_metadata": Base.metadata}
        )
        diff = produce_migrations(context, Base.metadata)
        assert diff.upgrade_ops.as_diffs() == []
