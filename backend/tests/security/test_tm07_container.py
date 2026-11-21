"""TM-07: the backend image is non-root and compose grants no extra privileges (T-109).

The Gazebo worker image (T-095) is not in the tree; these checks cover the image and
compose file that do exist.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.security

_REPO = Path(__file__).resolve().parents[3]


def test_backend_image_is_non_root() -> None:
    text = (_REPO / "docker/backend.Dockerfile").read_text(encoding="utf-8")
    assert "useradd --system" in text
    assert any(line.startswith("USER ") for line in text.splitlines())


def test_compose_is_not_privileged() -> None:
    text = (_REPO / "docker/compose.yaml").read_text(encoding="utf-8")
    assert "privileged:" not in text
    assert "docker.sock" not in text
    assert "read_only: true" in text
