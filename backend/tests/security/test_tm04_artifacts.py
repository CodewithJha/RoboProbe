"""TM-04: artefact paths cannot escape the store root (T-013a, T-109)."""

from __future__ import annotations

from pathlib import Path

import pytest

from roboprobe.core.errors import ValidationError
from roboprobe.store.artifacts import ArtifactRef, LocalArtifactStore

pytestmark = pytest.mark.security

_SHA = "ab" * 32


def test_relative_traversal_rejected(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    ref = ArtifactRef(
        sha256=_SHA,
        rel_path="../../etc/passwd",
        kind="log",
        size_bytes=1,
        media_type="text/plain",
    )
    with pytest.raises(ValidationError, match="escapes"):
        store.path(ref)


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    store = LocalArtifactStore(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret"
    secret.write_text("nope", encoding="utf-8")
    link = root / "sha256"
    link.symlink_to(outside, target_is_directory=True)
    ref = ArtifactRef(
        sha256=_SHA,
        rel_path=f"sha256/{secret.name}",
        kind="log",
        size_bytes=4,
        media_type="text/plain",
    )
    with pytest.raises(ValidationError, match="escapes"):
        store.open(ref)
