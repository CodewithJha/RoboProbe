"""Artefact GC / verify / retention (T-013b)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import update
from sqlalchemy.orm import sessionmaker
from tests.integration.store._seed import seed_campaign

from roboprobe.core.settings.storage import RetentionSettings
from roboprobe.core.types import RunStatus, Verdict
from roboprobe.store.artifacts import LocalArtifactStore
from roboprobe.store.ids import new_uuid
from roboprobe.store.maintenance import apply_retention, gc, verify
from roboprobe.store.orm import Base, RunRow
from roboprobe.store.records import ArtifactRecord
from roboprobe.store.uow import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.integration


def test_gc_dry_run_and_verify(pg_engine, tmp_path: Path) -> None:
    Base.metadata.drop_all(pg_engine)
    Base.metadata.create_all(pg_engine)
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    store = LocalArtifactStore(tmp_path / "art")
    blob = tmp_path / "a.log"
    blob.write_bytes(b"hello")
    ref = store.put(blob, "log")
    # orphan: no DB row
    (tmp_path / "art" / "sha256").mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    report = gc(
        lambda: SqlAlchemyUnitOfWork(factory, notify_channel="roboprobe_events"),
        store,
        RetentionSettings(),
        now=now,
        grace_s=0.0,
        dry_run=True,
    )
    assert report.dry_run is True
    assert store.path(ref).exists()
    corrupt = store.path(ref)
    corrupt.write_bytes(b"tampered")
    mismatches = verify(store)
    assert mismatches


def test_retention_keeps_failure_bags(pg_engine, tmp_path: Path) -> None:
    Base.metadata.drop_all(pg_engine)
    Base.metadata.create_all(pg_engine)
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    store = LocalArtifactStore(tmp_path / "art")
    old = datetime.now(UTC) - timedelta(days=40)
    with SqlAlchemyUnitOfWork(factory, notify_channel="roboprobe_events") as uow:
        cid, ids = seed_campaign(uow, n_runs=2)
        session = uow._session
        assert session is not None
        session.execute(
            update(RunRow)
            .where(RunRow.id == ids[0])
            .values(status=RunStatus.DONE.value, verdict=Verdict.FAIL.value, robustness=-0.2)
        )
        session.execute(
            update(RunRow)
            .where(RunRow.id == ids[1])
            .values(status=RunStatus.DONE.value, verdict=Verdict.PASS.value, robustness=0.2)
        )
        uow.artifacts.add(
            ArtifactRecord(
                id=new_uuid(),
                run_id=ids[0],
                campaign_id=cid,
                kind="bag",
                sha256="a" * 64,
                size_bytes=1,
                rel_path="sha256/aa/aa/fail.mcap",
                media_type="application/octet-stream",
                created_at=old,
            )
        )
        uow.artifacts.add(
            ArtifactRecord(
                id=new_uuid(),
                run_id=ids[1],
                campaign_id=cid,
                kind="bag",
                sha256="b" * 64,
                size_bytes=1,
                rel_path="sha256/bb/bb/pass.mcap",
                media_type="application/octet-stream",
                created_at=old,
            )
        )
        deleted = apply_retention(
            uow,
            store,
            RetentionSettings(bags_days=30, keep_failure_bags=True),
            now=datetime.now(UTC),
            dry_run=False,
        )
        bags = uow.artifacts.bags_for_retention()
    assert len(deleted) == 1
    assert len(bags) == 1
    assert bags[0].run_id == ids[0]
