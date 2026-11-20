"""Unit tests for LocalArtifactStore path confinement and hashing (T-013a)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from roboprobe.core.errors import ValidationError
from roboprobe.store.artifacts import LocalArtifactStore, NullArtifactStore

pytestmark = pytest.mark.unit


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def test_put_deduplicates_identical_content(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "art")
    a = _write(tmp_path / "a.bin", b"hello")
    b = _write(tmp_path / "b.bin", b"hello")
    campaign, run = uuid4(), uuid4()
    r1 = store.put(a, "log", run_id=run, campaign_id=campaign)
    r2 = store.put(b, "log", run_id=run, campaign_id=campaign)
    assert r1.sha256 == r2.sha256
    blobs = [p for p in (tmp_path / "art" / "sha256").rglob("*") if p.is_file()]
    assert len(blobs) == 1
    digest = hashlib.sha256(b"hello").hexdigest()
    assert r1.sha256 == digest
    assert store.path(r1).read_bytes() == b"hello"


def test_path_rejects_traversal(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "art")
    src = _write(tmp_path / "ok.log", b"x")
    ref = store.put(src, "log")
    evil = ref.model_copy(update={"rel_path": "../../etc/passwd"})
    with pytest.raises(ValidationError):
        store.path(evil)
    abs_ref = ref.model_copy(update={"rel_path": "/etc/passwd"})
    with pytest.raises(ValidationError):
        store.path(abs_ref)


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    root = tmp_path / "art"
    store = LocalArtifactStore(root)
    outside = tmp_path / "secret"
    outside.write_text("nope", encoding="utf-8")
    trap = root / "sha256" / "ab" / "cd"
    trap.mkdir(parents=True)
    link = trap / ("a" * 64 + ".log")
    link.symlink_to(outside)
    ref_src = _write(tmp_path / "t.log", b"x")
    ref = store.put(ref_src, "log")
    escaped = ref.model_copy(
        update={"rel_path": link.relative_to(root).as_posix(), "sha256": "a" * 64}
    )
    with pytest.raises(ValidationError):
        store.path(escaped)


def test_null_store_rejects_open() -> None:
    store = NullArtifactStore()
    ref = store.put(Path("missing"), "log")
    with pytest.raises(ValidationError):
        store.open(ref)
