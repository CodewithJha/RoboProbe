"""TM-15: shared manifests store a hostname hash, not the hostname (T-043, T-109)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from roboprobe.runner.manifest import ManifestBuilder, hash_hostname

pytestmark = pytest.mark.security


def test_manifest_hashes_hostname(tmp_path: Path) -> None:
    hostname = "lab-workstation.internal"
    material = tmp_path / "world.yaml"
    material.write_text("robots: 1\n", encoding="utf-8")
    manifest = (
        ManifestBuilder()
        .with_ids(run_id=uuid4(), campaign_id=uuid4())
        .with_backend("kinematic2d")
        .with_space("warehouse_v1", "3f9a1c2b7d10")
        .with_task("warehouse_delivery_v1", "a" * 64)
        .with_sut_profile("tb4_nav2_default", "b" * 16)
        .with_scenario("a1b2c3d4e5f67890", {"corridor_width_m": 2.0})
        .with_seeds(7)
        .with_materialized_files({"world.yaml": material}, workdir=tmp_path)
        .with_config_snapshot({"oracles": {}})
        .with_host(hostname=hostname, cpu="cpu", cores=2, ram_gb=8.0)
        .with_timing(wall_s=1.0, sim_s=1.0)
        .with_code(version="0.0.0", git_sha="abc", dirty=False, uv_lock_sha256="c" * 64)
        .build()
    )
    host = manifest["host"]
    assert isinstance(host, dict)
    assert host["hostname_hash"] == hash_hostname(hostname)
    assert hostname not in str(manifest)
