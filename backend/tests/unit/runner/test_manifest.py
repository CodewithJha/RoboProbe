"""Provenance ManifestBuilder (T-043)."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from roboprobe.core.seeding import LOCALIZATION, PERCEPTION, SENSOR, SIMULATOR, derive_seed
from roboprobe.runner.manifest import (
    GIT_SHA_ENV,
    ManifestBuilder,
    hash_hostname,
    hash_uv_lock,
    resolve_git_metadata,
)
from roboprobe.scenario._documents import schema_validator

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[4]


def _k2d_manifest(tmp_path: Path, *, hostname: str = "secret-host.local") -> dict[str, object]:
    material = tmp_path / "world.yaml"
    material.write_text("robots: 1\n", encoding="utf-8")
    run_seed = 1849302231
    return (
        ManifestBuilder()
        .with_ids(run_id=uuid4(), campaign_id=uuid4())
        .with_backend("kinematic2d")
        .with_space("warehouse_v1", "3f9a1c2b7d10")
        .with_task("warehouse_delivery_v1", "a" * 64)
        .with_sut_profile("tb4_nav2_default", "b" * 16)
        .with_scenario("a1b2c3d4e5f67890", {"corridor_width_m": 2.0})
        .with_seeds(run_seed)
        .with_materialized_files({"world.yaml": material}, workdir=tmp_path)
        .with_config_snapshot(
            {
                "oracles": {"clearance": {"d_min": 0.05}},
                "backends.kinematic2d": {"dt": 0.05},
            }
        )
        .with_host(hostname=hostname, cpu="test-cpu", cores=4, ram_gb=16.0)
        .with_timing(wall_s=10.0, sim_s=8.0)
        .with_code(
            version="0.0.1",
            git_sha="3c1e9a7",
            dirty=False,
            uv_lock_sha256=hash_uv_lock(REPO / "backend" / "uv.lock"),
        )
        .build()
    )


def test_manifest_validates_against_schema_for_k2d(tmp_path: Path) -> None:
    manifest = _k2d_manifest(tmp_path)
    schema_validator("manifest").validate(manifest)
    assert manifest["manifest_schema_version"] == 1
    assert manifest["backend"]["name"] == "kinematic2d"
    assert "oracles" in manifest["config_snapshot"]
    assert "backends.kinematic2d" in manifest["config_snapshot"]


def test_no_absolute_paths_or_raw_hostnames(tmp_path: Path) -> None:
    hostname = "lab-hostname.internal"
    manifest = _k2d_manifest(tmp_path, hostname=hostname)
    blob = json.dumps(manifest)
    assert hostname not in blob
    assert manifest["host"]["hostname_hash"] == hash_hostname(hostname)
    for key in manifest["materialized"]:
        assert not Path(key).is_absolute()
        assert not key.startswith("/")


def test_derived_seeds_match_derive_seed(tmp_path: Path) -> None:
    run_seed = 99
    material = tmp_path / "f.txt"
    material.write_text("x", encoding="utf-8")
    manifest = (
        ManifestBuilder()
        .with_ids(run_id=uuid4(), campaign_id=uuid4())
        .with_backend("kinematic2d")
        .with_space("s", "v")
        .with_task("t", "c" * 64)
        .with_sut_profile("p", "d" * 16)
        .with_scenario("hashhashhashhash", {})
        .with_seeds(run_seed)
        .with_materialized_files({"f.txt": material})
        .with_config_snapshot({"oracles": {}})
        .with_host(hostname="h", cpu="c", cores=1, ram_gb=1.0)
        .with_timing(wall_s=1.0, sim_s=1.0)
        .with_code(uv_lock_sha256="e" * 64, git_sha="abc", dirty=False)
        .build()
    )
    seeds = manifest["seeds"]
    assert seeds["run"] == run_seed
    assert seeds["sensor"] == derive_seed(run_seed, SENSOR)
    assert seeds["perception"] == derive_seed(run_seed, PERCEPTION)
    assert seeds["simulator"] == derive_seed(run_seed, SIMULATOR)
    assert seeds["localization"] == derive_seed(run_seed, LOCALIZATION)


def test_git_sha_from_env_not_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(GIT_SHA_ENV, "deadbeef")
    monkeypatch.setenv("ROBOPROBE_GIT_DIRTY", "true")
    sha, dirty = resolve_git_metadata()
    assert sha == "deadbeef"
    assert dirty is True
