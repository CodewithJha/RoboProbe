"""Alembic config must set path_separator (pytest treats warnings as errors)."""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

BACKEND_ROOT = Path(__file__).resolve().parents[3]


def test_alembic_ini_path_separator() -> None:
    cfg = ConfigParser()
    read = cfg.read(BACKEND_ROOT / "alembic.ini")
    assert read
    assert cfg.get("alembic", "path_separator") == "os"
