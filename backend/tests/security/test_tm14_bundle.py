"""TM-14: imported bundles reject absolute paths, traversal and links (T-014, T-109)."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
import zstandard as zstd
from tests.fakes.store import InMemoryUnitOfWork

from roboprobe.core.errors import ValidationError
from roboprobe.store.artifacts import LocalArtifactStore
from roboprobe.store.bundle import import_bundle

pytestmark = pytest.mark.security


def _pack(members: dict[str, tuple[bytes, int]], dest: Path) -> Path:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, (data, typ) in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.type = chr(typ) if isinstance(typ, int) else typ
            tar.addfile(info, io.BytesIO(data))
    dest.write_bytes(zstd.ZstdCompressor().compress(buf.getvalue()))
    return dest


@pytest.mark.parametrize(
    "name",
    ["../escape.txt", "/etc/passwd", "link"],
)
def test_malicious_member_rejected(tmp_path: Path, name: str) -> None:
    typ = tarfile.SYMTYPE if name == "link" else tarfile.REGTYPE
    payload = b"x" if typ == tarfile.REGTYPE else b""
    archive = _pack({name: (payload, typ)}, tmp_path / "bad.tar.zst")
    with pytest.raises(ValidationError):
        import_bundle(
            archive,
            InMemoryUnitOfWork(),
            LocalArtifactStore(tmp_path / "artifacts"),
        )
