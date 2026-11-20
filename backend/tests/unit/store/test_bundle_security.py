"""Security checks for campaign bundle extraction (T-014, TM-14)."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from uuid import UUID

import pytest
import zstandard as zstd
from tests.fakes.store import InMemoryUnitOfWork

from roboprobe.core.errors import ValidationError
from roboprobe.core.settings.storage import BundleSettings
from roboprobe.core.types import CampaignStatus, RunStatus
from roboprobe.store.artifacts import ArtifactRef, LocalArtifactStore
from roboprobe.store.bundle import BUNDLE_JSON, export_campaign, import_bundle
from roboprobe.store.ids import new_uuid
from roboprobe.store.records import (
    ArtifactRecord,
    CampaignRecord,
    RunRecord,
    SpaceRecord,
    SutProfileRecord,
)


def _pack(members: dict[str, bytes], dest: Path) -> Path:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    dest.write_bytes(zstd.ZstdCompressor().compress(buf.getvalue()))
    return dest


def _seed(uow: InMemoryUnitOfWork, store: LocalArtifactStore, tmp: Path) -> UUID:
    sut_id = f"p-{new_uuid()}"
    space_id = f"s-{new_uuid()}"
    uow.sut_profiles.add(
        SutProfileRecord(id=sut_id, backend="kinematic2d", config={}, config_hash="h")
    )
    uow.spaces.add(SpaceRecord(id=space_id, version="v", name="n", definition={}))
    cid = new_uuid()
    uow.campaigns.add(
        CampaignRecord(
            id=cid,
            name="c",
            space_id=space_id,
            space_version="v",
            sut_profile_id=sut_id,
            backend="kinematic2d",
            strategy_id="S-RANDOM",
            seed=1,
            budget=10,
            oracle_config={},
            status=CampaignStatus.COMPLETED,
        )
    )
    rid = new_uuid()
    uow.runs.import_many(
        [
            RunRecord(
                id=rid,
                campaign_id=cid,
                ordinal=0,
                repeat_index=0,
                backend="kinematic2d",
                scenario_hash="h0",
                scenario_values={"i": 0},
                x_unit=(0.1,),
                seed=0,
                phase="explore",
                proposal={},
                tags=(),
                replay_of=None,
                status=RunStatus.DONE,
                priority=100,
                attempt=1,
                worker_id=None,
                verdict=None,
                robustness=0.5,
                primary_failure=None,
                warnings=(),
                metrics={},
                infra_error=None,
                manifest={"host": {"hostname": "lab-host-01", "cores": 4}},
            )
        ]
    )
    blob = tmp / "payload.bin"
    blob.write_bytes(b"trace-bytes")
    ref = store.put(blob, "log", run_id=rid, campaign_id=cid)
    uow.artifacts.add(
        ArtifactRecord(
            id=ref.id,
            run_id=rid,
            campaign_id=cid,
            kind=ref.kind,
            sha256=ref.sha256,
            size_bytes=ref.size_bytes,
            rel_path=ref.rel_path,
            media_type=ref.media_type,
        )
    )
    return cid


def test_rejects_path_traversal(tmp_path: Path) -> None:
    archive = _pack({"../evil.txt": b"x"}, tmp_path / "bad.tar.zst")
    with (
        InMemoryUnitOfWork() as uow,
        pytest.raises(ValidationError, match=r"traversal|absolute"),
    ):
        import_bundle(
            archive,
            uow,
            LocalArtifactStore(tmp_path / "arts"),
            settings=BundleSettings(),
        )


def test_rejects_symlink(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name="link")
        info.type = tarfile.SYMTYPE
        info.linkname = "target"
        tar.addfile(info)
    archive = tmp_path / "sym.tar.zst"
    archive.write_bytes(zstd.ZstdCompressor().compress(buf.getvalue()))
    with InMemoryUnitOfWork() as uow, pytest.raises(ValidationError, match="link"):
        import_bundle(
            archive,
            uow,
            LocalArtifactStore(tmp_path / "arts"),
            settings=BundleSettings(),
        )


def test_rejects_wrong_member_hash(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "arts")
    with InMemoryUnitOfWork() as uow:
        cid = _seed(uow, store, tmp_path)
        out = tmp_path / "ok.tar.zst"
        export_campaign(cid, uow, store, out, settings=BundleSettings())

    dctx = zstd.ZstdDecompressor()
    with (
        out.open("rb") as raw,
        dctx.stream_reader(raw) as reader,
        tarfile.open(fileobj=reader, mode="r|") as tar,
    ):
        members: dict[str, bytes] = {}
        while True:
            member = tar.next()
            if member is None:
                break
            extracted = tar.extractfile(member)
            assert extracted is not None
            members[member.name] = extracted.read()
    manifest = json.loads(members[BUNDLE_JSON])
    first = next(iter(manifest["files"]))
    manifest["files"][first] = "0" * 64
    members[BUNDLE_JSON] = (json.dumps(manifest) + "\n").encode()
    bad = _pack(members, tmp_path / "tampered.tar.zst")
    with InMemoryUnitOfWork() as uow, pytest.raises(ValidationError, match="hash mismatch"):
        import_bundle(bad, uow, LocalArtifactStore(tmp_path / "arts2"))


def test_export_import_roundtrip_inmemory(tmp_path: Path) -> None:
    """Export then import into a fresh in-memory UoW reproduces rows and blobs."""
    src = LocalArtifactStore(tmp_path / "src")
    dst = LocalArtifactStore(tmp_path / "dst")
    settings = BundleSettings()
    shared = InMemoryUnitOfWork()
    with shared as uow:
        cid = _seed(uow, src, tmp_path)
        out = tmp_path / "camp.tar.zst"
        export_campaign(cid, uow, src, out, settings=settings)
        uow.commit()

    fresh = InMemoryUnitOfWork()
    with fresh as uow:
        imported = import_bundle(out, uow, dst, on_conflict="fail", settings=settings)
        assert imported == cid
        camp = uow.campaigns.get(cid)
        assert camp is not None
        runs = uow.runs.list_for_campaign(cid).items
        assert len(runs) == 1
        arts = uow.artifacts.list_for_run(runs[0].id)
        assert len(arts) == 1
        data = dst.path(
            ArtifactRef(
                id=arts[0].id,
                sha256=arts[0].sha256,
                rel_path=arts[0].rel_path,
                kind=arts[0].kind,
                size_bytes=arts[0].size_bytes,
                media_type=arts[0].media_type,
            )
        ).read_bytes()
        assert data == b"trace-bytes"
        again = import_bundle(out, uow, dst, on_conflict="skip", settings=settings)
        assert again == cid


def test_export_hashes_hostname(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "arts")
    with InMemoryUnitOfWork() as uow:
        cid = _seed(uow, store, tmp_path)
        out = tmp_path / "camp.tar.zst"
        export_campaign(cid, uow, store, out, settings=BundleSettings())
    dctx = zstd.ZstdDecompressor()
    with (
        out.open("rb") as raw,
        dctx.stream_reader(raw) as reader,
        tarfile.open(fileobj=reader, mode="r|") as tar,
    ):
        while True:
            member = tar.next()
            if member is None:
                break
            if member.name != "rows/runs.jsonl":
                continue
            extracted = tar.extractfile(member)
            assert extracted is not None
            row = json.loads(extracted.read().decode())
            host = row["manifest"]["host"]
            assert "hostname" not in host
            assert "hostname_hash" in host
            assert len(host["hostname_hash"]) == BundleSettings().hostname_hash_hex
            return
    pytest.fail("runs.jsonl missing")
