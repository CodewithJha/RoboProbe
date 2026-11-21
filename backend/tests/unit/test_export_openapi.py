"""OpenAPI export is deterministic and matches the committed snapshot (T-084b)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "export_openapi.py"
_SNAPSHOT = Path(__file__).resolve().parents[3] / "api" / "openapi.json"


def _exporter():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("export_openapi", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_two_exports_are_byte_identical() -> None:
    exporter = _exporter()
    assert exporter.render_openapi() == exporter.render_openapi()


def test_committed_snapshot_matches_app() -> None:
    rendered = _exporter().render_openapi()
    assert _SNAPSHOT.read_text(encoding="utf-8") == rendered
    assert rendered.endswith("\n")
    assert '"openapi": "3.1.0"' in rendered
