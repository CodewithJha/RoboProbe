"""Artefact GC, hash verify, and bag retention (docs/11 §7, docs/30 RB-08).

Implements: T-013b, FR-STO-002
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from roboprobe.core.settings.storage import RetentionSettings
from roboprobe.core.types import Verdict
from roboprobe.store.artifacts import SHA256_HEX_LENGTH, LocalArtifactStore
from roboprobe.store.ports import UnitOfWork

__all__ = ["GcReport", "Mismatch", "apply_retention", "find_orphans", "gc", "verify"]

UowFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True, slots=True)
class Mismatch:
    """A blob whose content hash does not match its filename."""

    path: Path
    expected: str
    actual: str


@dataclass(frozen=True, slots=True)
class GcReport:
    """What GC would do (or did)."""

    orphans: tuple[Path, ...]
    retained_bags_deleted: tuple[UUID, ...]
    dry_run: bool


def find_orphans(
    store: LocalArtifactStore,
    referenced: frozenset[str],
    *,
    now: datetime,
    grace_s: float,
) -> tuple[Path, ...]:
    """Blobs with no ``artifacts`` row and mtime older than ``grace_s``."""
    cutoff = now.timestamp() - grace_s
    found: list[Path] = []
    for path in store.iter_blobs():
        digest = path.stem
        if len(digest) != SHA256_HEX_LENGTH:
            digest = path.name.split(".")[0]
        if digest in referenced:
            continue
        if path.stat().st_mtime >= cutoff:
            continue
        found.append(path)
    return tuple(found)


def verify(store: LocalArtifactStore) -> list[Mismatch]:
    """Re-hash every blob and report filename mismatches."""
    bad: list[Mismatch] = []
    for path in store.iter_blobs():
        expected = path.name.split(".")[0]
        actual = _sha256(path)
        if actual != expected:
            bad.append(Mismatch(path=path, expected=expected, actual=actual))
    return bad


def apply_retention(
    uow: UnitOfWork,
    store: LocalArtifactStore,
    policy: RetentionSettings,
    *,
    now: datetime,
    dry_run: bool,
) -> tuple[UUID, ...]:
    """Drop bag rows (and files when unreferenced) past ``bags_days``.

    Never deletes bags of FAIL runs when ``keep_failure_bags`` is true.
    """
    deleted: list[UUID] = []
    cutoff = now - timedelta(days=policy.bags_days)
    for bag in uow.artifacts.bags_for_retention():
        created = bag.created_at
        if created is None or created >= cutoff:
            continue
        if bag.run_id is None:
            continue
        run = uow.runs.get(bag.run_id)
        if run is None:
            continue
        if policy.keep_failure_bags and run.verdict is Verdict.FAIL:
            continue
        deleted.append(bag.id)
        if not dry_run:
            uow.artifacts.delete(bag.id)
    return tuple(deleted)


def gc(  # noqa: PLR0913 - clock, grace and dry-run are explicit test seams.
    uow_factory: UowFactory,
    store: LocalArtifactStore,
    policy: RetentionSettings,
    *,
    now: datetime,
    grace_s: float,
    dry_run: bool,
) -> GcReport:
    """Apply retention then delete unreferenced blobs older than ``grace_s``."""
    with uow_factory() as uow:
        retained = apply_retention(uow, store, policy, now=now, dry_run=dry_run)
        referenced = uow.artifacts.sha256_set()
        if not dry_run:
            uow.commit()
        else:
            uow.rollback()
    orphans = find_orphans(store, referenced, now=now, grace_s=grace_s)
    if not dry_run:
        for path in orphans:
            path.unlink(missing_ok=True)
    return GcReport(orphans=orphans, retained_bags_deleted=retained, dry_run=dry_run)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
