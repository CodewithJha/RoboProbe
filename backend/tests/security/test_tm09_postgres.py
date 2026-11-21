"""TM-09: Postgres is not published on a public address (T-005b, T-109)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.security


def test_db_port_is_loopback_only() -> None:
    text = (Path(__file__).resolve().parents[3] / "docker/compose.yaml").read_text(encoding="utf-8")
    published = [line.strip() for line in text.splitlines() if "ports:" in line or ":5432" in line]
    assert any(line.startswith("ports:") for line in published)
    for line in published:
        if line.startswith("ports:"):
            assert "127.0.0.1:" in line
            assert "0.0.0.0:" not in line
