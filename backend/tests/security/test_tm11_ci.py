"""TM-11: workflows do not use pull_request_target and keep least privilege (T-109)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.security

_WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"


def test_workflows_are_least_privilege() -> None:
    for path in sorted(_WORKFLOWS.glob("*.yml")):
        lines = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith("#")
        ]
        text = "\n".join(lines)
        assert "pull_request_target" not in text, path.name
        assert "permissions:" in text, path.name
