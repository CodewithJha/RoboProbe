"""Shell round-trip for backup and restore (T-128)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_REPO = Path(__file__).resolve().parents[3]
_URL = "postgresql://roboprobe@127.0.0.1:5432/postgres"


def test_backup_restore_round_trip() -> None:
    if shutil.which("psql") is None or shutil.which("pg_dump") is None:
        pytest.skip("PostgreSQL client tools are not installed")
    probe = subprocess.run(  # noqa: S603 - fixed psql and local URL
        ["psql", _URL, "-v", "ON_ERROR_STOP=1", "-c", "SELECT 1"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip(probe.stderr.strip() or "PostgreSQL is not reachable")
    script = _REPO / "tests" / "integration" / "test_backup_restore.sh"
    completed = subprocess.run(  # noqa: S603 - fixed bash and repository script
        ["bash", str(script)],  # noqa: S607
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
