#!/usr/bin/env python3
"""Generate deterministic demo/test datasets for RoboProbe (T-107, NFR-MNT-001).

The script creates data **through application services** so every seed respects the
domain invariants: scenario space registration, campaign creation, inline execution,
the real analysis pipeline, risk mapping and a tiny experiment.  Two dataset sizes are
available:

``small``
    One 60-run kinematic2d campaign on ``warehouse_v1`` with exactly three failure
    modes, one final analysis, one risk map and one linked experiment. The result is
    exported as ``seed_small.sql`` plus a compact artefact
    tarball for the three medoid traces.

``large``
    A 10 000-run analytic campaign on ``multi_mode_6d`` used by performance tests.

The ``small`` dataset is intended to be committed under ``backend/tests/fixtures/db``
and loaded by ``backend/tests/fixtures/db/load_seed.py``.  Regenerating it from the same
``--seed`` produces the same logical rows: UUIDv7 generation is replaced by a fixed
counter and wall-clock timestamps are normalised after ``pg_dump``.

Usage::

    backend/.venv/bin/python scripts/seed_demo.py --size small \
        --seed 20261119 --database-url postgresql+psycopg://... \
        --export-sql backend/tests/fixtures/db/seed_small.sql \
        --export-artifacts backend/tests/fixtures/db/seed_small_artifacts.tar.zst

Layer: tooling (not imported by the application).
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, NotRequired, TypedDict, cast, override
from uuid import UUID

import numpy as np
import uuid_utils
import zstandard
from sqlalchemy import MetaData, Table, exists, inspect, select, text
from sqlalchemy.engine import make_url

from roboprobe.analysis import pipeline as analysis_pipeline
from roboprobe.analysis.base import AnalysisKind
from roboprobe.analysis.ports import AnalysisArtifactStore, AnalysisUnitOfWork
from roboprobe.bootstrap import build_cli_services
from roboprobe.bootstrap._infra import UowFactory, build_infrastructure
from roboprobe.bootstrap.experiments import SqlExperimentWriter
from roboprobe.cli import experiment as experiment_module
from roboprobe.cli.campaign import _ensure_sut, create_campaign_from_config, run_inline
from roboprobe.cli.db import upgrade_head
from roboprobe.cli.experiment import _resolve_key
from roboprobe.cli.space import register_space
from roboprobe.core.clock import FakeClock, SystemClock
from roboprobe.core.errors import ModelFitError
from roboprobe.core.settings import RoboProbeSettings, load_settings
from roboprobe.core.settings.selection import GpDefaults
from roboprobe.core.types import CampaignStatus, JsonValue
from roboprobe.experiments.planner import CampaignSpec, ExperimentDesign
from roboprobe.experiments.runner import ExperimentRunner
from roboprobe.risk import RiskMapper, VolumeEstimator, robustness_score
from roboprobe.risk.mapper import RiskSlice
from roboprobe.runner import worker as worker_module
from roboprobe.runner.manifest import ManifestBuilder
from roboprobe.scenario.repo_root import discover_repo_root
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.sut_profile import load_sut_profile
from roboprobe.selection.surrogate import RobustnessGP
from roboprobe.store import ids as store_ids
from roboprobe.store.artifacts import LocalArtifactStore
from roboprobe.store.engine import create_engine_from_settings
from roboprobe.store.ids import new_uuid
from roboprobe.store.mapping import artifact_record
from roboprobe.store.orm import ArtifactRow
from roboprobe.store.records import AnalysisRecord, ArtifactRecord, CampaignRecord, RiskMapRecord
from roboprobe.store.uow import SqlAlchemyUnitOfWork

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
FIXTURE_DIR: Final = REPO_ROOT / "backend" / "tests" / "fixtures" / "db"

DEFAULT_SEED: Final = 20261119
SMALL_RUNS: Final = 60
SMALL_MODES: Final = 3
LARGE_RUNS: Final = 10_000
_LARGE_BATCH_SIZE: Final = 256
_LARGE_WORKERS: Final = 8
FIXTURE_SLICE_RESOLUTION: Final = 8
FIXTURE_VOLUME_SAMPLES: Final = 256
MAX_ARTIFACT_BYTES: Final = 2 * 1024 * 1024

_FIXED_UUID7_MS: Final = 1_795_000_000_000
"""2026-11-19T...Z — the documented fixture seed date."""
_FIXED_TIMESTAMP: Final = datetime(2026, 11, 19, tzinfo=UTC)
_TIMESTAMP_RANK_STEP: Final = timedelta(milliseconds=1)

_SMALL_EXPERIMENT_ID: Final = "seed_demo_small"
_LARGE_CAMPAIGN_NAME: Final = "seed-demo-large"


# --------------------------------------------------------------------------------------
# Determinism helpers
# --------------------------------------------------------------------------------------
def install_deterministic_uuid7() -> None:
    """Replace ``uuid_utils.uuid7`` with a deterministic counter-based UUIDv7.

    All application UUIDs flow through :func:`roboprobe.store.ids.new_uuid`, which calls
    ``uuid_utils.uuid7`` at run time.  Patching the module attribute therefore covers
    ORM column defaults, repositories and artefact references without touching the
    application code.
    """
    counter = itertools.count()
    rand_multiplier = 0x9E3779B97F4A7C15
    rand_mask = (1 << 62) - 1

    def uuid7() -> uuid.UUID:
        n = next(counter)
        timestamp_ms = _FIXED_UUID7_MS + n // 0x1000
        rand_a = n % 0x1000
        rand_b = (n * rand_multiplier) & rand_mask
        value = (timestamp_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
        return uuid.UUID(int=value)

    uuid_utils.uuid7 = uuid7  # type: ignore[assignment]


def install_fixture_manifest_builder() -> None:
    """Canonicalise provenance manifests before they are hashed and stored.

    ``ManifestBuilder`` captures the host, wall-clock timing and repository metadata,
    which differ between machines and regeneration runs.  The fixture wrapper keeps
    the same schema and provenance fields but pins those volatile values so the
    manifest hash, ``artifacts.rel_path`` and the archive stay consistent.
    """

    class _FixtureManifestBuilder(ManifestBuilder):
        def with_host(
            self,
            *,
            hostname: str | None = None,
            cpu: str | None = None,
            cores: int | None = None,
            ram_gb: float | None = None,
        ) -> ManifestBuilder:
            del hostname, cpu, cores, ram_gb
            return super().with_host(
                hostname="fixture-host", cpu="fixture-cpu", cores=1, ram_gb=0.0
            )

        def with_timing(
            self, *, wall_s: float, sim_s: float, rtf_mean: float | None = None
        ) -> ManifestBuilder:
            del wall_s, sim_s, rtf_mean
            return super().with_timing(wall_s=0.0, sim_s=0.0)

        def with_code(
            self,
            *,
            version: str | None = None,
            git_sha: str | None = None,
            dirty: bool | None = None,
            uv_lock_sha256: str | None = None,
        ) -> ManifestBuilder:
            del version, git_sha, dirty, uv_lock_sha256
            return super().with_code(
                version="fixture",
                git_sha="0" * 40,
                dirty=False,
                uv_lock_sha256="0" * 64,
            )

    worker_module.ManifestBuilder = _FixtureManifestBuilder  # type: ignore[attr-defined]


def normalise_dump(text: str) -> str:
    """Replace volatile timestamps and pg_dump session tokens in a ``--column-inserts`` dump.

    Timestamps are mapped to ``2026-11-19T00:00:00Z`` plus one millisecond per distinct
    value (sorted), which preserves ordering while making the output byte-stable.
    """
    text = re.sub(r"^\\(?:un)?restrict .*$\n?", "", text, flags=re.MULTILINE)

    sql_pattern = re.compile(r"'(?P<value>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)\+00'")
    json_pattern = re.compile(
        r'"(?P<value>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)(?:Z|\+00:00)"'
    )

    sql_values = sorted({m.group("value") for m in sql_pattern.finditer(text)})
    json_values = sorted({m.group("value") for m in json_pattern.finditer(text)})
    all_values = sorted(set(sql_values) | set(json_values))
    ranks = {value: index for index, value in enumerate(all_values)}

    def sql_repl(match: re.Match[str]) -> str:
        stamp = _FIXED_TIMESTAMP + _TIMESTAMP_RANK_STEP * ranks[match.group("value")]
        return f"'{stamp.strftime('%Y-%m-%d %H:%M:%S.%f')}+00'"

    def json_repl(match: re.Match[str]) -> str:
        stamp = _FIXED_TIMESTAMP + _TIMESTAMP_RANK_STEP * ranks[match.group("value")]
        return f'"{stamp.strftime("%Y-%m-%dT%H:%M:%S.%f")}Z"'

    text = sql_pattern.sub(sql_repl, text)
    text = json_pattern.sub(json_repl, text)

    # Worker ids are ``host:pid:slot`` and differ on every machine.  Map each distinct
    # value to a stable placeholder (both SQL literals and JSON strings).
    worker_pattern = re.compile(r"""(['"])([A-Za-z0-9][A-Za-z0-9._-]*:\d+:\d+)\1""")
    workers = sorted({m.group(2) for m in worker_pattern.finditer(text)})
    worker_map = {value: f"seed-worker:1000:{index}" for index, value in enumerate(workers)}

    def worker_repl(match: re.Match[str]) -> str:
        quote = match.group(1)
        return f"{quote}{worker_map[match.group(2)]}{quote}"

    text = worker_pattern.sub(worker_repl, text)
    for table in ("runs", "oracle_results"):
        prefix = f"INSERT INTO public.{table} "
        pattern = re.compile(rf"^(?:{re.escape(prefix)}[^\n]*\n)+", re.MULTILINE)
        text = pattern.sub(lambda match: "".join(sorted(match[0].splitlines(keepends=True))), text)
    return text


# --------------------------------------------------------------------------------------
# Settings / database helpers
# --------------------------------------------------------------------------------------
def _settings(
    database_url: str,
    *,
    workdir_root: Path,
    artifact_root: Path,
    benchmark_function: str | None = None,
) -> RoboProbeSettings:

    overrides: dict[str, object] = {
        "database.url": database_url,
        "storage.workdir_root": str(workdir_root),
        "storage.artifact_root": str(artifact_root),
        "observability.metrics_enabled": False,
        "risk.slice_resolution": FIXTURE_SLICE_RESOLUTION,
        "risk.volume_samples": FIXTURE_VOLUME_SAMPLES,
        "backends.kinematic2d.model_file": str(
            REPO_ROOT / "configs" / "backends" / "kinematic2d_v1.yaml"
        ),
        "backends.gazebo_nav2.perception_model_file": str(
            REPO_ROOT / "configs" / "perception" / "oakd_lowlight_v1.yaml"
        ),
        "worker.poll_interval_s": 0.05,
        "runner.tick_interval_s": 0.05,
        # One campaign at a time keeps run/UUID insertion order stable and avoids
        # two inline workers binding the same health-port range.
        "experiments.max_concurrent_campaigns": 1,
    }
    if benchmark_function is not None:
        overrides["selection.benchmarks.function"] = benchmark_function
    return load_settings(overrides)


def _upgrade_schema(settings: RoboProbeSettings) -> None:
    """Apply pending migrations (safe on a fresh database; no destructive reset)."""
    upgrade_head(settings)


def _finalise_fixture_rows(
    settings: RoboProbeSettings,
    campaign_ids: Sequence[UUID],
    experiment_ids: Sequence[UUID] = (),
) -> None:
    """Make runtime metadata deterministic, scoped to the seeded campaigns.

    * drops worker heartbeats and ``runs.worker_id`` (host/PID values),
    * omits transient outbox events (SSE history is runtime state), and
    * pins run/campaign/analysis timestamps by ordinal with fixed phase offsets.

    Content-addressed artefacts and real run outcomes are untouched.
    """
    ids = list(campaign_ids)
    eids = list(experiment_ids)
    if not ids:
        return
    engine = create_engine_from_settings(settings.database)
    try:
        with engine.begin() as connection:
            worker_ids = [
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT DISTINCT worker_id FROM runs "
                        "WHERE campaign_id = ANY(:ids) AND worker_id IS NOT NULL"
                    ),
                    {"ids": ids},
                )
            ]
            connection.execute(
                text("UPDATE runs SET worker_id = NULL WHERE campaign_id = ANY(:ids)"),
                {"ids": ids},
            )
            if worker_ids:
                connection.execute(
                    text("DELETE FROM workers WHERE id = ANY(:ids)"),
                    {"ids": worker_ids},
                )
            connection.execute(
                text(
                    "DELETE FROM events WHERE campaign_id = ANY(:ids) "
                    "OR (topic = 'worker.updated' AND payload->>'worker_id' = ANY(:wids))"
                ),
                {"ids": ids, "wids": worker_ids},
            )
            params = {"base": _FIXED_TIMESTAMP, "ids": ids}
            connection.execute(
                text(
                    "UPDATE runs SET "
                    "enqueued_at = CAST(:base AS timestamptz) + ordinal * interval '1 second', "
                    "claimed_at = CAST(:base AS timestamptz) + ordinal * interval '1 second' "
                    "+ interval '100 milliseconds', "
                    "started_at = CAST(:base AS timestamptz) + ordinal * interval '1 second' "
                    "+ interval '200 milliseconds', "
                    "finished_at = CAST(:base AS timestamptz) + ordinal * interval '1 second' "
                    "+ interval '300 milliseconds' "
                    "WHERE campaign_id = ANY(:ids)"
                ),
                params,
            )
            connection.execute(
                text(
                    "UPDATE campaigns SET created_at = :base, "
                    "started_at = CAST(:base AS timestamptz) + interval '1 second', "
                    "finished_at = CAST(:base AS timestamptz) + interval '1 hour' "
                    "WHERE id = ANY(:ids)"
                ),
                params,
            )
            connection.execute(
                text(
                    "UPDATE analyses SET created_at = :base, "
                    "finished_at = CAST(:base AS timestamptz) + interval '5 minutes' "
                    "WHERE campaign_id = ANY(:ids)"
                ),
                params,
            )
            connection.execute(
                text(
                    "UPDATE failure_modes SET updated_at = CAST(:base AS timestamptz) "
                    "+ interval '5 minutes' WHERE campaign_id = ANY(:ids)"
                ),
                params,
            )
            connection.execute(
                text("UPDATE artifacts SET created_at = :base WHERE campaign_id = ANY(:ids)"),
                params,
            )
            connection.execute(
                text("UPDATE strategy_states SET updated_at = :base WHERE campaign_id = ANY(:ids)"),
                params,
            )
            if eids:
                connection.execute(
                    text(
                        "UPDATE experiments SET created_at = :base, "
                        "finished_at = CAST(:base AS timestamptz) + interval '1 hour' "
                        "WHERE id = ANY(:eids)"
                    ),
                    {"base": _FIXED_TIMESTAMP, "eids": eids},
                )
            connection.execute(
                text("UPDATE scenario_spaces SET created_at = :base"),
                {"base": _FIXED_TIMESTAMP},
            )
            connection.execute(
                text("UPDATE sut_profiles SET created_at = :base"),
                {"base": _FIXED_TIMESTAMP},
            )
    finally:
        engine.dispose()


def _database_is_empty(settings: RoboProbeSettings) -> bool:
    """Refuse to seed any database that already has application data."""
    engine = create_engine_from_settings(settings.database)
    try:
        with engine.connect() as connection:
            metadata = MetaData()
            for name in inspect(connection).get_table_names(schema="public"):
                if name == "alembic_version":
                    continue
                table = Table(name, metadata, schema="public")
                if connection.scalar(select(exists(select(1).select_from(table)))):
                    return False
            return True
    finally:
        engine.dispose()


def _write_large_campaign_config(path: Path, seed: int) -> None:
    payload = {
        "schema_version": 1,
        "name": _LARGE_CAMPAIGN_NAME,
        "space": {"id": "multi_mode_6d"},
        "sut_profile_id": "benchmark_default",
        "backend": "benchmark",
        "strategy": {"id": "S-RANDOM", "seed": seed},
        "budget": LARGE_RUNS,
        "repeats": 1,
        "batch_size": _LARGE_BATCH_SIZE,
        "start": True,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------------------
# Dataset generation
# --------------------------------------------------------------------------------------
class SmallSeedResult(TypedDict):
    """Identifiers and counts produced by the small fixture generator."""

    campaign_id: UUID
    runs: int
    modes: list[str]
    analysis_id: UUID
    risk_map_id: UUID
    experiment_id: UUID
    comparison_metrics: JsonValue
    medoid_run_ids: list[UUID]
    campaign_seconds: float
    analysis_seconds: float
    artifact_bytes: NotRequired[int]
    sql_sha256: NotRequired[str]
    sql_bytes: NotRequired[int]


class LargeSeedResult(TypedDict):
    """Identifiers and counts produced by the benchmark generator."""

    campaign_id: UUID
    runs: int
    seconds: float


class _FixtureExperimentWriter(SqlExperimentWriter):
    """``SqlExperimentWriter`` variant for fixture generation.

    * injects ``schema_version`` into the stored design (the comparison route
      validates ``ExperimentDesign`` from it), and
    * pins the campaign seed to the requested fixture seed instead of the planner's
      64-bit derived seed (sklearn estimators require a uint32 ``random_state``).
    """

    def __init__(self, make_uow: UowFactory, requested_seed: int) -> None:
        super().__init__(make_uow)
        self._requested_seed = requested_seed

    @override
    def add_experiment(self, *, name: str, design: dict[str, JsonValue], status: str) -> UUID:
        enriched: dict[str, JsonValue] = {"schema_version": 1, **design}
        return super().add_experiment(name=name, design=enriched, status=status)

    @override
    def add_campaign(self, spec: CampaignSpec, experiment_id: UUID) -> UUID:
        pinned = spec.model_copy(update={"seed": self._requested_seed})
        return super().add_campaign(pinned, experiment_id)


def _run_small_experiment(
    settings: RoboProbeSettings, seed: int, strategy: str, root: Path
) -> tuple[UUID, UUID, dict[str, JsonValue], float]:
    register_space(
        root / "configs" / "scenario_spaces" / "warehouse_v1.yaml",
        settings,
        base_dir=root,
    )
    space = ScenarioSpace.from_yaml(
        root / "configs" / "scenario_spaces" / "warehouse_v1.yaml", base_dir=root
    )
    profile = load_sut_profile(root / "configs" / "sut_profiles" / "k2d_default.yaml", strict=False)
    key = _resolve_key(space, profile.config_hash, "kinematic2d")

    design = ExperimentDesign.model_validate(
        {
            "schema_version": 1,
            "id": _SMALL_EXPERIMENT_ID,
            "name": "Seed demo small (60 runs)",
            "backend": "kinematic2d",
            "space": {"id": "warehouse_v1"},
            "sut_profile_id": "k2d_default",
            "strategies": [{"id": strategy}],
            "seeds": {"root": seed, "count": 1},
            "budget": SMALL_RUNS,
            "batch_size": 4,
            "metrics": ["MET-01", "MET-03"],
        }
    )

    services = build_cli_services(settings)
    _ensure_sut(services, "k2d_default", "kinematic2d")
    clock = FakeClock(_FIXED_TIMESTAMP)
    writer = _FixtureExperimentWriter(services.make_uow, seed)

    def drive(campaign_id: UUID) -> CampaignStatus:
        services.campaigns.start(campaign_id)
        return run_inline(campaign_id, settings, workers=1)

    runner = ExperimentRunner(writer, settings.experiments, clock, drive, new_uuid=new_uuid)
    started = time.monotonic()
    try:
        experiment_id, comparison = runner.start(design, key)
        elapsed = time.monotonic() - started
        campaigns = writer.list_campaigns(experiment_id)
    finally:
        services.close()
    if len(campaigns) != 1:
        msg = f"small experiment must own exactly one campaign, found {len(campaigns)}"
        raise RuntimeError(msg)
    campaign_id = cast("CampaignRecord", campaigns[0]).id
    return campaign_id, experiment_id, comparison, elapsed


def seed_small(
    settings: RoboProbeSettings, seed: int, strategy: str = "S-RANDOM"
) -> SmallSeedResult:
    """Create the small dataset and return its identifiers and counts.

    The 60-run kinematic2d campaign **is** the experiment campaign: the design has a
    single strategy and one seed, so the fixture contains exactly one campaign and one
    experiment with a populated comparison.  A second tiny experiment would have added
    extra campaigns/runs and violated the doc 18 §5 shape.
    """
    # ``pipeline`` and the experiment writer bind ``uuid4`` at import time; patch the
    # module attributes so analysis/mode/campaign ids follow the deterministic sequence.
    analysis_pipeline.uuid4 = new_uuid  # type: ignore[attr-defined]
    experiment_module.uuid4 = new_uuid  # type: ignore[attr-defined]

    root = discover_repo_root()
    campaign_id, experiment_id, comparison, elapsed = _run_small_experiment(
        settings, seed, strategy, root
    )

    def load_space(space_id: str, version: str) -> ScenarioSpace:
        return ScenarioSpace.from_yaml(
            root / "configs" / "scenario_spaces" / f"{space_id}.yaml", base_dir=root
        )

    analysis_started = time.monotonic()
    infra = build_infrastructure(settings)
    try:
        with infra.uow_factory() as uow:
            report = analysis_pipeline.analyze_campaign(
                campaign_id,
                cast("AnalysisUnitOfWork", uow),
                cast("AnalysisArtifactStore", infra.artifact_store),
                kind=AnalysisKind.FULL,
                settings=settings.analysis,
                risk=settings.risk,
                clock=FakeClock(_FIXED_TIMESTAMP),
                load_space=load_space,
            )
            uow.commit()
        analysis_elapsed = time.monotonic() - analysis_started

        with infra.uow_factory() as uow:
            modes = uow.modes.list_for_campaign(campaign_id)
            analyses = uow.analyses.list_for_campaign(campaign_id)
            if report.status != "OK":
                msg = f"analysis status {report.status}: {report.warnings}"
                raise RuntimeError(msg)
            if len(modes) != SMALL_MODES:
                msg = (
                    f"expected {SMALL_MODES} failure modes, found {len(modes)}: "
                    f"{[m.code for m in modes]}"
                )
                raise RuntimeError(msg)
            analysis = analyses[-1]
            risk_map = _persist_risk_map(
                uow,
                infra.artifact_store,
                settings,
                analysis,
                seed,
            )
            uow.commit()
            mode_codes = [m.code for m in modes]
            medoid_run_ids = [m.medoid_run_id for m in modes if m.medoid_run_id is not None]
    finally:
        infra.close()

    return {
        "campaign_id": campaign_id,
        "runs": SMALL_RUNS,
        "modes": mode_codes,
        "analysis_id": analysis.id,
        "risk_map_id": risk_map,
        "experiment_id": experiment_id,
        "comparison_metrics": comparison.get("metrics", []),
        "medoid_run_ids": medoid_run_ids,
        "campaign_seconds": round(elapsed, 2),
        "analysis_seconds": round(analysis_elapsed, 2),
    }


def seed_large(settings: RoboProbeSettings, seed: int) -> LargeSeedResult:
    """Create the 10 000-run analytic performance dataset."""
    runner_settings = settings.runner.model_copy(
        update={
            "max_batch_size": _LARGE_BATCH_SIZE,
            "inflight_factor": 2 * _LARGE_BATCH_SIZE / _LARGE_WORKERS,
        }
    )
    settings = settings.model_copy(update={"runner": runner_settings})
    root = discover_repo_root()
    register_space(
        root / "configs" / "scenario_spaces" / "multi_mode_6d.yaml",
        settings,
        base_dir=root,
    )
    with tempfile.TemporaryDirectory(prefix="roboprobe-seed-") as tmp:
        config = Path(tmp) / "large.yaml"
        _write_large_campaign_config(config, seed)
        started = time.monotonic()
        campaign_id = create_campaign_from_config(config, settings)
        status = run_inline(campaign_id, settings, workers=_LARGE_WORKERS)
        elapsed = time.monotonic() - started
    if str(status) != "COMPLETED":
        msg = f"large campaign finished with status {status}"
        raise RuntimeError(msg)
    return {
        "campaign_id": campaign_id,
        "runs": LARGE_RUNS,
        "seconds": round(elapsed, 2),
    }


def _persist_risk_map(
    uow: SqlAlchemyUnitOfWork,
    artifact_store: LocalArtifactStore,
    settings: RoboProbeSettings,
    analysis: AnalysisRecord,
    seed: int,
) -> UUID:
    """Compute risk slices, store them as JSON and insert the missing ``risk_maps`` row.

    The analysis pipeline computes slices in memory for FULL runs but does not persist
    them; the API expects a JSON artefact.  This helper closes that gap for fixtures
    without changing production analysis behaviour (documented assumption in the PR).
    """
    campaign_id = analysis.campaign_id
    root = discover_repo_root()
    campaign = uow.campaigns.get(campaign_id)
    if campaign is None:
        msg = "campaign disappeared while seeding risk map"
        raise RuntimeError(msg)
    space = ScenarioSpace.from_yaml(
        root / "configs" / "scenario_spaces" / f"{campaign.space_id}.yaml",
        base_dir=root,
    )

    xs: list[list[float]] = []
    ys: list[float] = []
    cursor: str | None = None
    while True:
        page = uow.runs.list_for_campaign(campaign_id, cursor=cursor)
        for row in page.items:
            if row.robustness is not None and np.isfinite(row.robustness):
                xs.append([float(v) for v in row.x_unit])
                ys.append(float(row.robustness))
        cursor = page.next_cursor
        if cursor is None:
            break
    if not xs:
        msg = "no runs with robustness values for risk map"
        raise RuntimeError(msg)

    gp = RobustnessGP(
        space.dim,
        seed=seed,
        gp=GpDefaults(),
        metrics=None,
        clock=SystemClock(),
    )
    try:
        gp.fit(np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64))
    except ModelFitError as exc:
        msg = f"risk GP fit failed: {exc}"
        raise RuntimeError(msg) from exc

    mapper = RiskMapper(gp, space, settings.risk.thresholds)
    slices = mapper.all_pair_slices(
        space.nominal_values(), resolution=settings.risk.slice_resolution
    )
    volumes = VolumeEstimator().estimate(mapper, n=settings.risk.volume_samples, seed=seed)
    payload = [_slice_payload(item) for item in slices]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)
        tmp_path = Path(handle.name)
    try:
        ref = artifact_store.put(tmp_path, kind="analysis", campaign_id=campaign_id)
    finally:
        tmp_path.unlink(missing_ok=True)

    summary_volumes = (analysis.summary or {}).get("volumes")
    if isinstance(summary_volumes, dict) and "safe" in summary_volumes:
        volume_json: dict[str, JsonValue] = dict(summary_volumes)
    else:
        volume_json = {
            "safe": volumes.safe,
            "uncertain": volumes.uncertain,
            "failure": volumes.failure,
            "safe_ci": list(volumes.safe_ci),
            "uncertain_ci": list(volumes.uncertain_ci),
            "failure_ci": list(volumes.failure_ci),
            "n": volumes.n,
            "seed": volumes.seed,
        }
    volume_json["robustness_score"] = robustness_score(volumes)

    artifact_id = store_ids.new_uuid()
    uow.artifacts.add(
        ArtifactRecord(
            id=artifact_id,
            run_id=None,
            campaign_id=campaign_id,
            kind="analysis",
            sha256=ref.sha256,
            size_bytes=ref.size_bytes,
            rel_path=ref.rel_path,
            media_type=ref.media_type,
        )
    )
    risk_id = store_ids.new_uuid()
    uow.risk_maps.add(
        RiskMapRecord(
            id=risk_id,
            campaign_id=campaign_id,
            analysis_id=analysis.id,
            n_obs=len(xs),
            thresholds=settings.risk.thresholds.model_dump(),
            volumes=volume_json,
            robustness_score=robustness_score(volumes),
            slices_artifact=artifact_id,
        )
    )
    return risk_id


def _slice_payload(item: RiskSlice) -> dict[str, JsonValue]:
    return {
        "x_param": item.x_param,
        "y_param": item.y_param,
        "x_values": [float(v) for v in item.x_values],
        "y_values": [float(v) for v in item.y_values],
        "log_x": bool(item.log_x),
        "log_y": bool(item.log_y),
        "p_fail": [[float(v) for v in row] for row in item.p_fail],
        "mean": [[float(v) for v in row] for row in item.mean],
        "std": [[float(v) for v in row] for row in item.std],
        "region": [[int(v) for v in row] for row in item.region],
        "anchor": dict(item.anchor),
        "resolution": int(item.p_fail.shape[0]),
    }


# --------------------------------------------------------------------------------------
# Artefact pruning / tarball
# --------------------------------------------------------------------------------------
def prune_artifacts(
    settings: RoboProbeSettings,
    campaign_id: UUID,
    medoid_run_ids: Sequence[UUID],
) -> list[str]:
    """Keep campaign-level artefacts and the medoid runs' files; delete the rest."""
    keep_runs = set(medoid_run_ids)
    artifact_root = Path(settings.storage.artifact_root)
    infra = build_infrastructure(settings)
    try:
        with infra.uow_factory() as uow:
            rows = _list_all_artifacts(uow)
            kept_rows = [row for row in rows if row.run_id is None or row.run_id in keep_runs]
            dropped_rows = [row for row in rows if row not in kept_rows]
            kept_paths = {row.rel_path for row in kept_rows}
            for row in dropped_rows:
                uow.artifacts.delete(row.id)
            uow.commit()
        # Content-addressed blobs are shared by digest: only unlink paths that no
        # retained row still references.
        for rel_path in {row.rel_path for row in dropped_rows} - kept_paths:
            (artifact_root / rel_path).unlink(missing_ok=True)
    finally:
        infra.close()
    return sorted(kept_paths)


def _list_all_artifacts(uow: SqlAlchemyUnitOfWork) -> list[ArtifactRecord]:
    # The fixture needs all artifacts, including campaign-level rows.
    session = uow._require()
    rows = session.scalars(select(ArtifactRow).order_by(ArtifactRow.created_at)).all()
    return [artifact_record(row) for row in rows]


def write_artifact_tarball(artifact_root: Path, rel_paths: Iterable[str], out: Path) -> int:
    """Write a deterministic ``.tar.zst`` with ``rel_paths`` under ``artifact_root``."""
    paths = sorted(set(rel_paths))
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as handle:
        tar_path = Path(handle.name)
    try:
        with tarfile.open(tar_path, "w") as archive:
            for rel in paths:
                source = artifact_root / rel
                if not source.is_file():
                    msg = f"retained artefact blob is missing: {source}"
                    raise RuntimeError(msg)
                info = archive.gettarinfo(str(source), arcname=rel)
                info.mtime = 0
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                with source.open("rb") as stream:
                    archive.addfile(info, stream)
        with tar_path.open("rb") as tar_stream, out.open("wb") as dest:
            compressor = zstandard.ZstdCompressor(level=19, write_checksum=False)
            compressor.copy_stream(tar_stream, dest)
    finally:
        tar_path.unlink(missing_ok=True)
    return out.stat().st_size


# --------------------------------------------------------------------------------------
# SQL export
# --------------------------------------------------------------------------------------
def _dsn(database_url: str) -> str:

    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        msg = f"unsupported database backend {url.get_backend_name()!r}"
        raise ValueError(msg)
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def export_sql(database_url: str, out: Path, dump_cmd: str, dump_dbname: str | None = None) -> str:
    """Run ``pg_dump --data-only --column-inserts`` and write a normalised fixture."""
    command = [
        *shlex.split(dump_cmd),
        "--data-only",
        "--column-inserts",
        "--no-owner",
        "--no-privileges",
        "--exclude-table=alembic_version",
        "--exclude-table=public.events",
        "--exclude-table=public.events_id_seq",
        "--dbname",
        dump_dbname or _dsn(database_url),
    ]
    try:
        # Execute the configured pg_dump wrapper directly with argv.
        result = subprocess.run(command, check=True, capture_output=True, text=True)  # noqa: S603
    except subprocess.CalledProcessError as exc:
        # Never echo ``command``/``exc``: the DSN contains credentials.
        msg = f"pg_dump failed (exit {exc.returncode}); check the database and dump command"
        raise RuntimeError(msg) from None
    header = (
        "-- RoboProbe small demo fixture (T-107, doc 18 §5).\n"
        f"-- Generated by scripts/seed_demo.py --size small --seed {DEFAULT_SEED}.\n"
        "-- Load with backend/tests/fixtures/db/load_seed.py after `roboprobe db upgrade`.\n\n"
    )
    body = normalise_dump(result.stdout)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(header + body.rstrip() + "\n", encoding="utf-8")
    return hashlib.sha256(out.read_bytes()).hexdigest()


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    """Define arguments for dataset generation and export."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--size", choices=("small", "large"), required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--strategy", default="S-RANDOM", help="Small-dataset strategy id.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--workdir-root", type=Path, default=None)
    parser.add_argument("--artifact-root", type=Path, default=None)
    parser.add_argument("--export-sql", type=Path, default=None)
    parser.add_argument("--export-artifacts", type=Path, default=None)
    parser.add_argument(
        "--dump-cmd",
        default="pg_dump",
        help="pg_dump executable (may include a wrapper, e.g. 'docker exec pg pg_dump').",
    )
    parser.add_argument("--dump-dbname", help="Database name as seen by a pg_dump wrapper.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Generate the requested dataset and print its summary."""
    args = build_parser().parse_args(argv)
    install_deterministic_uuid7()
    install_fixture_manifest_builder()

    workdir_root = args.workdir_root or (REPO_ROOT / "data" / "seed" / "workdirs")
    artifact_root = args.artifact_root or (REPO_ROOT / "data" / "seed" / "artifacts")
    workdir_root.mkdir(parents=True, exist_ok=True)
    artifact_root.mkdir(parents=True, exist_ok=True)

    settings = _settings(
        args.database_url,
        workdir_root=workdir_root,
        artifact_root=artifact_root,
    )
    if not _database_is_empty(settings):
        print("Use a dedicated database with no application data.", file=sys.stderr)
        return 2
    _upgrade_schema(settings)

    if args.size == "small":
        small = seed_small(settings, args.seed, strategy=args.strategy)
        campaign_id = small["campaign_id"]
        rel_paths = prune_artifacts(settings, campaign_id, small["medoid_run_ids"])
        _finalise_fixture_rows(settings, [campaign_id], [small["experiment_id"]])
        if args.export_artifacts is not None:
            size = write_artifact_tarball(artifact_root, rel_paths, args.export_artifacts)
            small["artifact_bytes"] = size
            if size > MAX_ARTIFACT_BYTES:
                msg = f"artifact tarball is {size} bytes (> {MAX_ARTIFACT_BYTES})"
                raise RuntimeError(msg)
        if args.export_sql is not None:
            digest = export_sql(args.database_url, args.export_sql, args.dump_cmd, args.dump_dbname)
            small["sql_sha256"] = digest
            small["sql_bytes"] = args.export_sql.stat().st_size
        summary: SmallSeedResult | LargeSeedResult = small
    else:
        summary = seed_large(settings, args.seed)

    print(json.dumps(summary, indent=2, default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
