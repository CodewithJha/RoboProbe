"""TM-12: stored blobs and manifests carry SHA-256 (T-013a, T-043, T-109)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from roboprobe.store.artifacts import LocalArtifactStore

pytestmark = pytest.mark.security


def test_put_records_content_hash(tmp_path: Path) -> None:
    source = tmp_path / "trace.bin"
    payload = b"trace-bytes"
    source.write_bytes(payload)
    ref = LocalArtifactStore(tmp_path / "artifacts").put(source, "log")
    assert ref.sha256 == hashlib.sha256(payload).hexdigest()
    assert ref.size_bytes == len(payload)
