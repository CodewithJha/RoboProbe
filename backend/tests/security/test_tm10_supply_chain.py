"""TM-10: lockfile, pip-audit and digest-pinned images are present (T-006c, T-109)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.security

_REPO = Path(__file__).resolve().parents[3]


def test_lockfile_and_audit_job_exist() -> None:
    assert (_REPO / "backend/uv.lock").is_file()
    ci = (_REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "pip-audit" in ci
    assert "pnpm audit" in ci or "audit" in ci


def test_dockerfiles_pin_base_images_by_digest() -> None:
    dockerfile = (_REPO / "docker/backend.Dockerfile").read_text(encoding="utf-8")
    assert "@sha256:" in dockerfile
