"""Campaign export/import as ``.tar.zst`` (JSON Lines + artefacts).

Implements: T-014, FR-STO-003, NFR-SEC-003, TM-14, TM-15
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import zstandard as zstd
from pydantic import TypeAdapter

from roboprobe.core.errors import ConflictError, NotFoundError, ValidationError
from roboprobe.core.settings.storage import BundleSettings
from roboprobe.store.artifacts import ArtifactRef, ArtifactStore, LocalArtifactStore
from roboprobe.store.ports import UnitOfWork
from roboprobe.store.records import (
    AnalysisRecord,
    ArtifactRecord,
    CampaignRecord,
    OracleResultRecord,
    RiskMapRecord,
    RunRecord,
    SpaceRecord,
    StrategyStateRecord,
    SutProfileRecord,
)

__all__ = [
    "BUNDLE_JSON",
    "ROW_TABLES",
    "export_campaign",
    "import_bundle",
]

BUNDLE_JSON = "bundle.json"
_ROWS_DIR = "rows"
_BLOBS_DIR = "blobs"
_ROW_SCHEMA_VERSION = 1

ROW_TABLES: tuple[str, ...] = (
    "spaces",
    "sut_profiles",
    "campaigns",
    "runs",
    "oracle_results",
    "artifacts",
    "strategy_states",
    "analyses",
    "risk_maps",
)

_Conflict = Literal["skip", "fail"]


def export_campaign(  # noqa: PLR0915
    campaign_id: UUID,
    uow: UnitOfWork,
    store: ArtifactStore,
    out: Path,
    *,
    settings: BundleSettings | None = None,
) -> Path:
    """Write a portable ``.tar.zst`` for ``campaign_id`` under ``out``.

    Layout: ``bundle.json``, ``rows/<table>.jsonl``, ``blobs/<sha256>``.
    Hostnames in run manifests are hashed (TM-15).
    """
    cfg = settings or BundleSettings()
    campaign = uow.campaigns.get(campaign_id)
    if campaign is None:
        msg = "campaign not found"
        raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
    space = uow.spaces.get(campaign.space_id, campaign.space_version)
    if space is None:
        msg = "space not found"
        raise NotFoundError(
            msg, context={"space_id": campaign.space_id, "version": campaign.space_version}
        )
    sut = uow.sut_profiles.get(campaign.sut_profile_id)
    if sut is None:
        msg = "sut profile not found"
        raise NotFoundError(msg, context={"sut_profile_id": campaign.sut_profile_id})

    runs = _all_runs(uow, campaign_id)
    oracles = [row for run in runs for row in uow.oracle_results.list_for_run(run.id)]
    artifacts = _collect_artifacts(uow, campaign_id, runs)
    strategy = uow.strategy_states.get(campaign_id)
    analyses = list(uow.analyses.list_for_campaign(campaign_id))
    risk = uow.risk_maps.latest(campaign_id)
    if risk is not None and risk.slices_artifact is not None:
        slice_art = uow.artifacts.get(risk.slices_artifact)
        if slice_art is not None and all(a.id != slice_art.id for a in artifacts):
            artifacts.append(slice_art)

    rows: dict[str, list[dict[str, Any]]] = {
        "spaces": [_row_payload(space)],
        "sut_profiles": [_row_payload(sut)],
        "campaigns": [_row_payload(campaign)],
        "runs": [_row_payload(_sanitize_run(run, cfg.hostname_hash_hex)) for run in runs],
        "oracle_results": [_row_payload(row) for row in oracles],
        "artifacts": [_row_payload(row) for row in artifacts],
        "strategy_states": [] if strategy is None else [_row_payload(strategy)],
        "analyses": [_row_payload(row) for row in analyses],
        "risk_maps": [] if risk is None else [_row_payload(risk)],
    }

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="roboprobe-bundle-"))
    try:
        rows_dir = staging / _ROWS_DIR
        blobs_dir = staging / _BLOBS_DIR
        rows_dir.mkdir()
        blobs_dir.mkdir()
        file_hashes: dict[str, str] = {}
        for table, payloads in rows.items():
            rel = f"{_ROWS_DIR}/{table}.jsonl"
            path = staging / rel
            _write_jsonl(path, payloads)
            file_hashes[rel] = _sha256_file(path, cfg.read_chunk_bytes)

        for art in artifacts:
            blob_rel = f"{_BLOBS_DIR}/{art.sha256}"
            blob_path = staging / blob_rel
            src = store.path(
                ArtifactRef(
                    id=art.id,
                    sha256=art.sha256,
                    rel_path=art.rel_path,
                    kind=art.kind,
                    size_bytes=art.size_bytes,
                    media_type=art.media_type,
                    run_id=art.run_id,
                    campaign_id=art.campaign_id,
                )
            )
            if not src.is_file():
                msg = "artifact blob missing"
                raise NotFoundError(msg, context={"sha256": art.sha256, "path": str(src)})
            _copy_file(src, blob_path, cfg.read_chunk_bytes)
            digest = _sha256_file(blob_path, cfg.read_chunk_bytes)
            if digest != art.sha256:
                msg = "artifact hash mismatch on export"
                raise ValidationError(
                    msg, context={"sha256": art.sha256, "actual": digest, "rel_path": art.rel_path}
                )
            file_hashes[blob_rel] = digest

        manifest = {
            "format_version": cfg.format_version,
            "campaign_id": str(campaign_id),
            "row_counts": {table: len(payloads) for table, payloads in rows.items()},
            "files": file_hashes,
            "created_at": datetime.now(UTC).isoformat(),
        }
        bundle_json = staging / BUNDLE_JSON
        _write_manifest(bundle_json, manifest)
        file_hashes[BUNDLE_JSON] = _sha256_file(bundle_json, cfg.read_chunk_bytes)
        # Exclude self-hash from the verified files map stored in bundle.json.
        manifest["files"] = {k: v for k, v in file_hashes.items() if k != BUNDLE_JSON}
        _write_manifest(bundle_json, manifest)

        _pack_tar_zst(staging, out_path, cfg.read_chunk_bytes)
    finally:
        _rm_tree(staging)
    return out_path


def import_bundle(
    path: Path,
    uow: UnitOfWork,
    store: ArtifactStore,
    *,
    on_conflict: _Conflict = "fail",
    settings: BundleSettings | None = None,
) -> UUID:
    """Import a campaign bundle. Verifies hashes before any DB write (TM-14)."""
    cfg = settings or BundleSettings()
    if on_conflict not in ("skip", "fail"):
        msg = "on_conflict must be 'skip' or 'fail'"
        raise ValidationError(msg, context={"on_conflict": on_conflict})

    archive = Path(path)
    if not archive.is_file():
        msg = "bundle not found"
        raise NotFoundError(msg, context={"path": str(archive)})

    extracted = Path(tempfile.mkdtemp(prefix="roboprobe-bundle-in-"))
    try:
        members = _safe_extract(archive, extracted, cfg)
        manifest = _load_manifest(extracted / BUNDLE_JSON, cfg)
        _verify_member_hashes(extracted, manifest["files"], cfg)
        campaign_id = UUID(str(manifest["campaign_id"]))
        tables = _load_tables(extracted)
        return _apply_import(
            uow,
            store,
            campaign_id=campaign_id,
            tables=tables,
            blobs_dir=extracted / _BLOBS_DIR,
            on_conflict=on_conflict,
            settings=cfg,
            member_names=members,
        )
    finally:
        _rm_tree(extracted)


def _apply_import(  # noqa: PLR0912, PLR0913
    uow: UnitOfWork,
    store: ArtifactStore,
    *,
    campaign_id: UUID,
    tables: dict[str, list[dict[str, Any]]],
    blobs_dir: Path,
    on_conflict: _Conflict,
    settings: BundleSettings,
    member_names: set[str],
) -> UUID:
    existing = uow.campaigns.get(campaign_id)
    if existing is not None:
        if on_conflict == "skip":
            return campaign_id
        msg = "campaign already exists"
        raise ConflictError(msg, context={"campaign_id": str(campaign_id)})

    spaces = [_parse(SpaceRecord, row) for row in tables.get("spaces", [])]
    suts = [_parse(SutProfileRecord, row) for row in tables.get("sut_profiles", [])]
    campaigns = [_parse(CampaignRecord, row) for row in tables.get("campaigns", [])]
    runs = [_parse(RunRecord, row) for row in tables.get("runs", [])]
    oracles = [_parse(OracleResultRecord, row) for row in tables.get("oracle_results", [])]
    artifacts = [_parse(ArtifactRecord, row) for row in tables.get("artifacts", [])]
    strategies = [_parse(StrategyStateRecord, row) for row in tables.get("strategy_states", [])]
    analyses = [_parse(AnalysisRecord, row) for row in tables.get("analyses", [])]
    risk_maps = [_parse(RiskMapRecord, row) for row in tables.get("risk_maps", [])]

    if len(campaigns) != 1 or campaigns[0].id != campaign_id:
        msg = "bundle campaign row mismatch"
        raise ValidationError(msg, context={"campaign_id": str(campaign_id)})

    for art in artifacts:
        blob_name = f"{_BLOBS_DIR}/{art.sha256}"
        if blob_name not in member_names and not (blobs_dir / art.sha256).is_file():
            msg = "bundle missing artifact blob"
            raise ValidationError(msg, context={"sha256": art.sha256})
        blob_path = blobs_dir / art.sha256
        digest = _sha256_file(blob_path, settings.read_chunk_bytes)
        if digest != art.sha256:
            msg = "artifact blob hash mismatch"
            raise ValidationError(msg, context={"sha256": art.sha256, "actual": digest})
        if art.size_bytes != blob_path.stat().st_size:
            msg = "artifact size mismatch"
            raise ValidationError(
                msg,
                context={
                    "sha256": art.sha256,
                    "expected": art.size_bytes,
                    "actual": blob_path.stat().st_size,
                },
            )

    # Blobs first (filesystem), then DB — on DB failure blobs are content-addressed and harmless.
    for art in artifacts:
        _materialize_blob(store, art, blobs_dir / art.sha256, settings.read_chunk_bytes)

    for space in spaces:
        if uow.spaces.get(space.id, space.version) is None:
            uow.spaces.add(space)
        elif on_conflict == "fail":
            msg = "space already exists"
            raise ConflictError(msg, context={"space_id": space.id, "version": space.version})
    for sut in suts:
        if uow.sut_profiles.get(sut.id) is None:
            uow.sut_profiles.add(sut)
        elif on_conflict == "fail":
            msg = "sut profile already exists"
            raise ConflictError(msg, context={"sut_profile_id": sut.id})

    uow.campaigns.add(campaigns[0])
    uow.runs.import_many(runs)
    by_run: dict[UUID, list[OracleResultRecord]] = {}
    for row in oracles:
        by_run.setdefault(row.run_id, []).append(row)
    for run_id, rows in by_run.items():
        uow.oracle_results.replace_for_run(run_id, rows)
    for art in artifacts:
        uow.artifacts.add(art)
    for state in strategies:
        uow.strategy_states.upsert(state)
    for analysis in analyses:
        uow.analyses.add(analysis)
    for risk in risk_maps:
        uow.risk_maps.add(risk)
    return campaign_id


def _materialize_blob(store: ArtifactStore, art: ArtifactRecord, src: Path, chunk: int) -> None:
    ref = ArtifactRef(
        id=art.id,
        sha256=art.sha256,
        rel_path=art.rel_path,
        kind=art.kind,
        size_bytes=art.size_bytes,
        media_type=art.media_type,
        run_id=art.run_id,
        campaign_id=art.campaign_id,
    )
    dest = store.path(ref)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return
    if isinstance(store, LocalArtifactStore):
        _copy_file(src, dest, chunk)
        return
    # Generic store: put() re-hashes; prefer path write when available.
    _copy_file(src, dest, chunk)


def _all_runs(uow: UnitOfWork, campaign_id: UUID) -> list[RunRecord]:
    out: list[RunRecord] = []
    cursor: str | None = None
    while True:
        page = uow.runs.list_for_campaign(campaign_id, cursor=cursor)
        out.extend(page.items)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    return out


def _collect_artifacts(
    uow: UnitOfWork, campaign_id: UUID, runs: Sequence[RunRecord]
) -> list[ArtifactRecord]:
    seen: set[UUID] = set()
    out: list[ArtifactRecord] = []
    for run in runs:
        for art in uow.artifacts.list_for_run(run.id):
            if art.id in seen:
                continue
            seen.add(art.id)
            out.append(art)
    _ = campaign_id
    return out


def _sanitize_run(run: RunRecord, hostname_hash_hex: int) -> RunRecord:
    if run.manifest is None:
        return run
    hashed = _hash_hostnames(dict(run.manifest), hostname_hash_hex)
    if not isinstance(hashed, dict):
        return run
    return run.model_copy(update={"manifest": dict(hashed)})


def _hash_hostnames(value: object, hex_len: int) -> object:
    if isinstance(value, Mapping):
        out: dict[str, object] = {}
        for key, item in value.items():
            if key in {"hostname", "host_name"} and isinstance(item, str):
                out["hostname_hash"] = hashlib.sha256(item.encode("utf-8")).hexdigest()[:hex_len]
            elif key == "host" and isinstance(item, Mapping):
                host = dict(item)
                raw_host = host.pop("hostname", None)
                if isinstance(raw_host, str):
                    host["hostname_hash"] = hashlib.sha256(raw_host.encode("utf-8")).hexdigest()[
                        :hex_len
                    ]
                out[key] = _hash_hostnames(host, hex_len)
            else:
                out[str(key)] = _hash_hostnames(item, hex_len)
        return out
    if isinstance(value, list):
        return [_hash_hostnames(item, hex_len) for item in value]
    return value


def _row_payload(record: object) -> dict[str, Any]:
    raw = record.model_dump(mode="json")  # type: ignore[attr-defined]
    data = dict(raw)
    data["schema_version"] = _ROW_SCHEMA_VERSION
    return data


def _parse[T](model: type[T], row: Mapping[str, Any]) -> T:
    payload = {k: v for k, v in row.items() if k != "schema_version"}
    return TypeAdapter(model).validate_python(payload)


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=str))
            handle.write("\n")


def _load_tables(root: Path) -> dict[str, list[dict[str, Any]]]:
    tables: dict[str, list[dict[str, Any]]] = {}
    for table in ROW_TABLES:
        path = root / _ROWS_DIR / f"{table}.jsonl"
        if not path.is_file():
            tables[table] = []
            continue
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                msg = "jsonl row must be an object"
                raise ValidationError(msg, context={"table": table})
            version = payload.get("schema_version", _ROW_SCHEMA_VERSION)
            if version != _ROW_SCHEMA_VERSION:
                msg = "unsupported row schema_version"
                raise ValidationError(msg, context={"table": table, "schema_version": version})
            rows.append(payload)
        tables[table] = rows
    return tables


def _load_manifest(path: Path, settings: BundleSettings) -> dict[str, Any]:
    if not path.is_file():
        msg = "bundle.json missing"
        raise ValidationError(msg, context={"path": str(path)})
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = "bundle.json must be an object"
        raise ValidationError(msg)
    version = int(raw.get("format_version", -1))
    if version != settings.format_version:
        msg = "unsupported bundle format_version"
        raise ValidationError(msg, context={"format_version": version})
    files = raw.get("files")
    if not isinstance(files, dict):
        msg = "bundle.json files map required"
        raise ValidationError(msg)
    return raw


def _verify_member_hashes(root: Path, files: Mapping[str, Any], settings: BundleSettings) -> None:
    for rel, expected in files.items():
        rel_s = str(rel)
        _reject_member_name(rel_s)
        path = root / rel_s
        if not path.is_file():
            msg = "bundle member missing"
            raise ValidationError(msg, context={"member": rel_s})
        actual = _sha256_file(path, settings.read_chunk_bytes)
        if actual != str(expected):
            msg = "bundle member hash mismatch"
            raise ValidationError(
                msg, context={"member": rel_s, "expected": expected, "actual": actual}
            )


def _safe_extract(archive: Path, dest: Path, settings: BundleSettings) -> set[str]:
    """Extract ``archive`` into ``dest`` with TM-14 checks; return member names."""
    names: set[str] = set()
    total = 0
    with archive.open("rb") as raw:
        dctx = zstd.ZstdDecompressor()
        with dctx.stream_reader(raw) as reader, tarfile.open(fileobj=reader, mode="r|") as tar:
            while True:
                member = tar.next()
                if member is None:
                    break
                name = member.name
                _reject_member_name(name)
                if member.issym() or member.islnk():
                    msg = "bundle must not contain links"
                    raise ValidationError(msg, context={"member": name})
                if not member.isreg():
                    msg = "bundle member must be a regular file"
                    raise ValidationError(msg, context={"member": name, "type": str(member.type)})
                size = member.size
                if size > settings.max_member_bytes:
                    msg = "bundle member too large"
                    raise ValidationError(
                        msg,
                        context={
                            "member": name,
                            "size": size,
                            "max_member_bytes": settings.max_member_bytes,
                        },
                    )
                total += size
                if total > settings.max_uncompressed_bytes:
                    msg = "bundle uncompressed size exceeds limit"
                    raise ValidationError(
                        msg,
                        context={
                            "total": total,
                            "max_uncompressed_bytes": settings.max_uncompressed_bytes,
                        },
                    )
                target = (dest / name).resolve()
                if not target.is_relative_to(dest.resolve()):
                    msg = "bundle path escapes destination"
                    raise ValidationError(msg, context={"member": name})
                target.parent.mkdir(parents=True, exist_ok=True)
                extracted = tar.extractfile(member)
                if extracted is None:
                    msg = "bundle member unreadable"
                    raise ValidationError(msg, context={"member": name})
                with extracted, target.open("wb") as out:
                    remaining = size
                    while remaining > 0:
                        chunk = extracted.read(min(settings.read_chunk_bytes, remaining))
                        if not chunk:
                            break
                        out.write(chunk)
                        remaining -= len(chunk)
                    if remaining != 0:
                        msg = "bundle member truncated"
                        raise ValidationError(msg, context={"member": name})
                names.add(name)
    return names


def _reject_member_name(name: str) -> None:
    if not name or name.startswith("/") or name.startswith("\\"):
        msg = "absolute paths forbidden in bundle"
        raise ValidationError(msg, context={"member": name})
    parts = Path(name).parts
    if any(part in {".", ".."} for part in parts):
        msg = "path traversal forbidden in bundle"
        raise ValidationError(msg, context={"member": name})
    if Path(name).is_absolute():
        msg = "absolute paths forbidden in bundle"
        raise ValidationError(msg, context={"member": name})


def _write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _pack_tar_zst(src_dir: Path, out: Path, chunk: int) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for path in sorted(src_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(src_dir).as_posix()
            tar.add(path, arcname=rel)
    cctx = zstd.ZstdCompressor(level=3)
    out.write_bytes(cctx.compress(buffer.getvalue()))
    _ = chunk


def _sha256_file(path: Path, chunk: int) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _copy_file(src: Path, dest: Path, chunk: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", dir=dest.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out, src.open("rb") as inp:
            while True:
                block = inp.read(chunk)
                if not block:
                    break
                out.write(block)
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _rm_tree(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file() or child.is_symlink():
            child.unlink(missing_ok=True)
        elif child.is_dir():
            child.rmdir()
    path.rmdir()
