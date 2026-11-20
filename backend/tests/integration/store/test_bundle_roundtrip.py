"""Campaign bundle export → import round-trip (T-014)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import delete
from tests.integration.store._seed import seed_campaign

from roboprobe.core.settings.storage import BundleSettings
from roboprobe.core.types import FailureClass, RunStatus, Verdict
from roboprobe.store.artifacts import ArtifactRef, LocalArtifactStore
from roboprobe.store.bundle import export_campaign, import_bundle
from roboprobe.store.orm import (
    ArtifactRow,
    CampaignRow,
    OracleResultRow,
    RunRow,
    ScenarioSpaceRow,
    SutProfileRow,
)
from roboprobe.store.records import ArtifactRecord, OracleResultRecord


@pytest.mark.integration
def test_bundle_roundtrip(uow_factory, tmp_path: Path) -> None:  # noqa: PLR0915
    src_store = LocalArtifactStore(tmp_path / "src_arts")
    dst_store = LocalArtifactStore(tmp_path / "dst_arts")
    settings = BundleSettings()

    with uow_factory() as uow:
        cid, run_ids = seed_campaign(uow, n_runs=1)
        rid = run_ids[0]
        blob = tmp_path / "trace.bin"
        blob.write_bytes(b"roundtrip-payload")
        ref = src_store.put(blob, "log", run_id=rid, campaign_id=cid)
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
        run_row = uow._require().get(RunRow, rid)
        assert run_row is not None
        run_row.status = RunStatus.DONE.value
        run_row.verdict = Verdict.PASS.value
        run_row.robustness = 0.25
        run_row.manifest = {"host": {"hostname": "ci-host"}}
        uow.oracle_results.replace_for_run(
            rid,
            [
                OracleResultRecord(
                    run_id=rid,
                    oracle_id="O-COLLISION",
                    failure_class=FailureClass.COL,
                    severity="failure",
                    violated=False,
                    robustness=0.25,
                )
            ],
        )
        uow.commit()

    out = tmp_path / "campaign.tar.zst"
    with uow_factory() as uow:
        export_campaign(cid, uow, src_store, out, settings=settings)

    with uow_factory() as uow:
        camp = uow.campaigns.get(cid)
        assert camp is not None
        space_id, space_version = camp.space_id, camp.space_version
        sut_id = camp.sut_profile_id
        session = uow._require()
        session.execute(delete(OracleResultRow).where(OracleResultRow.run_id == rid))
        session.execute(delete(ArtifactRow).where(ArtifactRow.campaign_id == cid))
        session.execute(delete(RunRow).where(RunRow.campaign_id == cid))
        session.execute(delete(CampaignRow).where(CampaignRow.id == cid))
        # Only this campaign's space/SUT — other integration tests may still hold warehouse_v1.
        session.execute(
            delete(ScenarioSpaceRow).where(
                ScenarioSpaceRow.id == space_id,
                ScenarioSpaceRow.version == space_version,
            )
        )
        session.execute(delete(SutProfileRow).where(SutProfileRow.id == sut_id))
        session.flush()

        imported = import_bundle(out, uow, dst_store, on_conflict="fail", settings=settings)
        assert imported == cid
        camp = uow.campaigns.get(cid)
        assert camp is not None
        runs = uow.runs.list_for_campaign(cid).items
        assert len(runs) == 1
        assert runs[0].id == rid
        assert runs[0].status is RunStatus.DONE
        assert runs[0].verdict is Verdict.PASS
        assert runs[0].manifest is not None
        host = runs[0].manifest["host"]
        assert isinstance(host, dict)
        assert "hostname" not in host
        assert "hostname_hash" in host
        arts = uow.artifacts.list_for_run(rid)
        assert len(arts) == 1
        assert arts[0].sha256 == ref.sha256
        dest = dst_store.path(
            ArtifactRef(
                id=arts[0].id,
                sha256=arts[0].sha256,
                rel_path=arts[0].rel_path,
                kind=arts[0].kind,
                size_bytes=arts[0].size_bytes,
                media_type=arts[0].media_type,
            )
        )
        assert dest.read_bytes() == b"roundtrip-payload"
        oracles = uow.oracle_results.list_for_run(rid)
        assert len(oracles) == 1
        assert oracles[0].oracle_id == "O-COLLISION"
        again = import_bundle(out, uow, dst_store, on_conflict="skip", settings=settings)
        assert again == cid
