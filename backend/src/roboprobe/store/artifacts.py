"""Local content-addressed artefact store (docs/11 §6, ADR-0008).

Implements: T-013a, FR-STO-002, NFR-SEC-003
"""

# ruff: noqa: D102, D107

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from roboprobe.core.errors import ValidationError
from roboprobe.store.ids import new_uuid
from roboprobe.store.orm import ARTIFACT_KINDS

__all__ = [
    "ARTIFACT_KINDS",
    "KIND_MEDIA",
    "SHA256_HEX_LENGTH",
    "ArtifactKind",
    "ArtifactRef",
    "ArtifactStore",
    "LocalArtifactStore",
    "NullArtifactStore",
]

SHA256_HEX_LENGTH = 64
HEX_PREFIX_LEN = 2

ArtifactKind = Literal[
    "trace",
    "bag",
    "log",
    "world",
    "params",
    "manifest",
    "figure",
    "report",
    "risk_slices",
    "analysis",
    "video",
    "bundle",
]

KIND_MEDIA: dict[str, tuple[str, str]] = {
    "trace": ("application/vnd.apache.parquet", ".parquet"),
    "bag": ("application/octet-stream", ".mcap"),
    "log": ("text/plain", ".log"),
    "world": ("application/xml", ".sdf"),
    "params": ("application/yaml", ".yaml"),
    "manifest": ("application/json", ".json"),
    "figure": ("image/svg+xml", ".svg"),
    "report": ("text/html", ".html"),
    "risk_slices": ("application/octet-stream", ".npz"),
    "analysis": ("application/json", ".json"),
    "video": ("video/mp4", ".mp4"),
    "bundle": ("application/zstd", ".tar.zst"),
}

_LINK_NAMES: dict[str, str] = {
    "trace": "trace.parquet",
    "bag": "bag.mcap",
    "log": "episode.log",
    "world": "world.sdf",
    "params": "nav2_params.yaml",
    "manifest": "manifest.json",
    "figure": "figure.svg",
    "report": "report.html",
    "risk_slices": "risk_slices.npz",
    "analysis": "analysis.json",
    "video": "episode.mp4",
    "bundle": "bundle.tar.zst",
}


class ArtifactRef(BaseModel):
    """Pointer to a stored blob (hash + relative path)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(default_factory=new_uuid)
    sha256: str
    rel_path: str
    kind: str
    size_bytes: int
    media_type: str
    run_id: UUID | None = None
    campaign_id: UUID | None = None


class ArtifactStore(Protocol):
    """Port: content-addressed blobs with confined paths."""

    def put(
        self,
        src: Path,
        kind: ArtifactKind,
        run_id: UUID | None = None,
        campaign_id: UUID | None = None,
    ) -> ArtifactRef: ...

    def open(self, ref: ArtifactRef) -> BinaryIO: ...

    def path(self, ref: ArtifactRef) -> Path: ...


class LocalArtifactStore:
    """Filesystem adapter under ``storage.artifact_root``."""

    def __init__(
        self,
        root: Path,
        *,
        recorder: Callable[[ArtifactRef], None] | None = None,
    ) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._recorder = recorder

    def put(
        self,
        src: Path,
        kind: ArtifactKind,
        run_id: UUID | None = None,
        campaign_id: UUID | None = None,
    ) -> ArtifactRef:
        if kind not in ARTIFACT_KINDS:
            msg = "unknown artifact kind"
            raise ValidationError(msg, context={"kind": kind})
        source = src.expanduser()
        if not source.is_file():
            msg = "artifact source is not a file"
            raise ValidationError(msg, context={"src": str(src)})
        media_type, ext = KIND_MEDIA[kind]
        digest, size = _hash_file(source)
        shard = digest[HEX_PREFIX_LEN : HEX_PREFIX_LEN * 2]
        rel = Path("sha256") / digest[:HEX_PREFIX_LEN] / shard / f"{digest}{ext}"
        dest = self._confine(self._root / rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            self._atomic_copy(source, dest)
        if run_id is not None and campaign_id is not None:
            self._link_run(campaign_id, run_id, kind, dest)
        ref = ArtifactRef(
            sha256=digest,
            rel_path=rel.as_posix(),
            kind=kind,
            size_bytes=size,
            media_type=media_type,
            run_id=run_id,
            campaign_id=campaign_id,
        )
        if self._recorder is not None:
            self._recorder(ref)
        return ref

    def open(self, ref: ArtifactRef) -> BinaryIO:
        return self.path(ref).open("rb")

    def path(self, ref: ArtifactRef) -> Path:
        if len(ref.sha256) != SHA256_HEX_LENGTH or any(
            ch not in "0123456789abcdef" for ch in ref.sha256
        ):
            msg = "invalid sha256"
            raise ValidationError(msg, context={"sha256": ref.sha256})
        return self._confine(self._root / ref.rel_path)

    def iter_blobs(self) -> tuple[Path, ...]:
        base = self._root / "sha256"
        if not base.exists():
            return ()
        return tuple(p for p in base.rglob("*") if p.is_file())

    def _confine(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self._root):
            msg = "path escapes artifact root"
            raise ValidationError(msg, context={"path": str(path), "root": str(self._root)})
        return resolved

    def _atomic_copy(self, src: Path, dest: Path) -> None:
        fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", dir=dest.parent)
        tmp = self._confine(Path(tmp_name))
        try:
            with os.fdopen(fd, "wb") as out, src.open("rb") as inp:
                while True:
                    chunk = inp.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            tmp.replace(dest)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def _link_run(self, campaign_id: UUID, run_id: UUID, kind: str, dest: Path) -> None:
        folder = self._confine(self._root / "runs" / str(campaign_id) / str(run_id))
        folder.mkdir(parents=True, exist_ok=True)
        link = self._confine(folder / _LINK_NAMES[kind])
        if link.exists() or link.is_symlink():
            return
        try:
            link.symlink_to(dest)
        except OSError:
            try:
                link.hardlink_to(dest)
            except OSError:
                link.write_text(dest.name, encoding="utf-8")


class NullArtifactStore:
    """Null Object store for tests that do not touch the filesystem."""

    def put(
        self,
        src: Path,
        kind: ArtifactKind,
        run_id: UUID | None = None,
        campaign_id: UUID | None = None,
    ) -> ArtifactRef:
        return ArtifactRef(
            sha256="0" * SHA256_HEX_LENGTH,
            rel_path="sha256/00/00/null.bin",
            kind=kind,
            size_bytes=0,
            media_type="application/octet-stream",
            run_id=run_id,
            campaign_id=campaign_id,
        )

    def open(self, ref: ArtifactRef) -> BinaryIO:
        msg = "NullArtifactStore has no blobs"
        raise ValidationError(msg, context={"sha256": ref.sha256})

    def path(self, ref: ArtifactRef) -> Path:
        msg = "NullArtifactStore has no blobs"
        raise ValidationError(msg, context={"sha256": ref.sha256})


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size
