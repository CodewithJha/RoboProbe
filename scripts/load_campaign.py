"""Measure real RoboProbe campaign and PostgreSQL scaling (T-130, NFR-SCAL-001)."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from tempfile import mkdtemp
from uuid import UUID

from sqlalchemy import Engine, MetaData, Table, exists, inspect, select, text

from roboprobe.cli.campaign import create_campaign_from_config
from roboprobe.cli.db import upgrade_head
from roboprobe.core.settings import RoboProbeSettings, load_settings
from roboprobe.store.engine import create_engine_from_settings

_PROFILES = {
    "benchmark": ("multi_mode_6d", "benchmark_default"),
    "kinematic2d": ("warehouse_v1", "k2d_default"),
}
_FULL_MATRIX = (1, 2, 4, 8)
_FULL_RUNS = 10_000
_REQUIRED_SCALE = 6.0
_DB_QUERY = text("""
SELECT
    (SELECT count(*) FROM pg_stat_activity
     WHERE datname = current_database() AND backend_type = 'client backend'
       AND pid <> pg_backend_pid()),
    (SELECT COALESCE(max(n_dead_tup), 0) FROM pg_stat_user_tables
     WHERE schemaname = 'public' AND relname = 'runs')
""")
_RUN_QUERY = text("""
SELECT
    count(*) FILTER (WHERE status = 'DONE'),
    count(DISTINCT ordinal) FILTER (WHERE status = 'DONE' AND ordinal BETWEEN 0 AND :last),
    count(*) - count(DISTINCT ordinal),
    COALESCE(sum(greatest(attempt - 1, 0)), 0),
    count(DISTINCT worker_id) FILTER (WHERE status = 'DONE'),
    count(*) FILTER (WHERE claimed_at IS NULL OR claimed_at < enqueued_at),
    percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM claimed_at - enqueued_at)),
    percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM claimed_at - enqueued_at))
FROM runs WHERE campaign_id = :campaign_id
""")


@dataclass(frozen=True)
class Measurement:
    """Summary for one measured worker count."""

    workers: int
    completed: int
    seconds: float
    runs_per_second: float
    claim_p50_ms: float
    claim_p95_ms: float
    peak_db_connections: int
    initial_dead_tuples: int
    peak_dead_tuples: int
    final_dead_tuples: int
    missing: int
    duplicates: int
    retries: int
    participating_workers: int


def _worker_counts(value: str) -> tuple[int, ...]:
    try:
        counts = tuple(int(item) for item in value.split(","))
    except ValueError as exc:
        msg = "worker counts must be comma-separated integers"
        raise argparse.ArgumentTypeError(msg) from exc
    if not counts or tuple(sorted(set(counts))) != counts or counts[0] < 1:
        msg = "worker counts must be positive, unique and increasing"
        raise argparse.ArgumentTypeError(msg)
    return counts


def _require_empty_database(engine: Engine) -> None:
    with engine.connect() as connection:
        for name in inspect(connection).get_table_names(schema="public"):
            if name == "alembic_version":
                continue
            table = Table(name, MetaData(), schema="public")
            if connection.scalar(select(exists(select(1).select_from(table)))):
                msg = "Use a dedicated empty database for the load test."
                raise ValueError(msg)


def _wait_for_workers(
    engine: Engine, backend: str, expected: int, deadline: float, interval: float
) -> None:
    query = text("SELECT count(*) FROM workers WHERE backend = :backend AND status = 'IDLE'")
    while time.monotonic() < deadline:
        with engine.connect() as conn:
            if int(conn.scalar(query, {"backend": backend}) or 0) == expected:
                return
        time.sleep(interval)
    msg = f"Expected {expected} idle {backend} workers before starting the campaign."
    raise RuntimeError(msg)


def _db_sample(engine: Engine) -> tuple[int, int]:
    with engine.connect() as conn:
        connections, dead_tuples = conn.execute(_DB_QUERY).one()
    return int(connections), int(dead_tuples)


def _run_process(
    executable: Path, arguments: Sequence[str], env: Mapping[str, str], log: Path
) -> subprocess.Popen[bytes]:
    with log.open("wb") as stream:
        return subprocess.Popen(  # noqa: S603 - fixed local executable and argument vector
            [str(executable), *arguments], env=env, stdout=stream, stderr=subprocess.STDOUT
        )


def _stop_processes(processes: Sequence[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _campaign(
    path: Path, settings: RoboProbeSettings, args: argparse.Namespace, workers: int
) -> UUID:
    space, sut = _PROFILES[args.backend]
    document = {
        "schema_version": 1,
        "name": f"t130_scaling_{workers}",
        "space": {"id": space},
        "sut_profile_id": sut,
        "backend": args.backend,
        "strategy": {"id": "S-RANDOM", "seed": args.seed},
        "budget": args.runs,
        "repeats": 1,
        "batch_size": args.batch,
        "start": True,
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return create_campaign_from_config(path, settings)


def _await_completion(
    engine: Engine,
    campaign_id: UUID,
    processes: Sequence[subprocess.Popen[bytes]],
    args: argparse.Namespace,
) -> tuple[int, int, int]:
    query = text("SELECT status FROM campaigns WHERE id = :id")
    deadline = time.monotonic() + args.timeout
    peak_connections = peak_dead_tuples = 0
    while time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            msg = "A RoboProbe subprocess exited before campaign completion."
            raise RuntimeError(msg)
        connections, dead_tuples = _db_sample(engine)
        peak_connections = max(peak_connections, connections)
        peak_dead_tuples = max(peak_dead_tuples, dead_tuples)
        with engine.connect() as conn:
            status = conn.scalar(query, {"id": campaign_id})
        if status == "COMPLETED":
            return peak_connections, peak_dead_tuples, dead_tuples
        if status in {"FAILED", "CANCELLED", "PAUSED"}:
            msg = f"Campaign {campaign_id} stopped with status {status}."
            raise RuntimeError(msg)
        time.sleep(args.sample_interval)
    msg = f"Campaign {campaign_id} exceeded the measurement timeout."
    raise RuntimeError(msg)


def _measure(
    settings: RoboProbeSettings, engine: Engine, args: argparse.Namespace, output: Path, count: int
) -> Measurement:
    env = {
        **os.environ,
        "ROBOPROBE_DATABASE__URL": settings.database.url.get_secret_value(),
        "ROBOPROBE_STORAGE__WORKDIR_ROOT": str(settings.storage.workdir_root),
        "ROBOPROBE_STORAGE__ARTIFACT_ROOT": str(settings.storage.artifact_root),
        "ROBOPROBE_SELECTION__BENCHMARKS__FUNCTION": "multi_mode_6d",
        "ROBOPROBE_RUNNER__TICK_INTERVAL_S": str(args.tick),
        "ROBOPROBE_RUNNER__MAX_BATCH_SIZE": str(args.batch),
        "ROBOPROBE_RUNNER__INFLIGHT_FACTOR": str(args.inflight_factor),
        "ROBOPROBE_WORKER__POLL_INTERVAL_S": str(args.tick),
        "ROBOPROBE_OBSERVABILITY__METRICS_ENABLED": "false",
    }
    executable = Path(sys.executable).with_name("roboprobe")
    space, _ = _PROFILES[args.backend]
    processes: list[subprocess.Popen[bytes]] = []
    try:
        processes.append(
            _run_process(executable, ["orchestrator"], env, output / "orchestrator.log")
        )
        for slot in range(count):
            worker_env = {**env, "ROBOPROBE_WORKER__ID_PREFIX": f"t130-{count}-{slot}"}
            worker_args = ["worker", "--backend", args.backend, "--space", space]
            processes.append(
                _run_process(executable, worker_args, worker_env, output / f"worker-{slot}.log")
            )
        _wait_for_workers(
            engine, args.backend, count, time.monotonic() + args.startup_timeout, args.tick
        )
        _, initial_dead_tuples = _db_sample(engine)
        started = time.monotonic()
        campaign = _campaign(output / "campaign.json", settings, args, count)
        peak_connections, peak_dead_tuples, final_dead_tuples = _await_completion(
            engine, campaign, processes, args
        )
        duration = time.monotonic() - started
        with engine.connect() as conn:
            done, distinct, duplicates, retries, participants, invalid_claims, p50, p95 = (
                conn.execute(_RUN_QUERY, {"campaign_id": campaign, "last": args.runs - 1}).one()
            )
        if invalid_claims or p50 is None or p95 is None:
            msg = f"Campaign {campaign} has missing or invalid claim timestamps."
            raise RuntimeError(msg)
        return Measurement(
            count,
            int(done),
            duration,
            int(done) / duration,
            float(p50) * 1000,
            float(p95) * 1000,
            peak_connections,
            initial_dead_tuples,
            peak_dead_tuples,
            final_dead_tuples,
            args.runs - int(distinct),
            int(duplicates),
            int(retries),
            int(participants),
        )
    finally:
        _stop_processes(processes)
        # These processes were stopped by this test. Remove their stale registrations from the
        # following trial's worker count without deleting any campaign or run evidence.
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE workers SET status = 'OFFLINE' WHERE id LIKE :prefix"),
                {"prefix": f"t130-{count}-%"},
            )


def _record(measurements: Sequence[Measurement], path: Path) -> None:
    baseline = measurements[0]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[field.name for field in fields(Measurement)] + ["speedup", "efficiency"],
        )
        writer.writeheader()
        for item in measurements:
            speedup = item.runs_per_second / baseline.runs_per_second
            efficiency = speedup / (item.workers / baseline.workers)
            writer.writerow({**asdict(item), "speedup": speedup, "efficiency": efficiency})
            print(
                f"{item.workers} workers: {item.runs_per_second:.2f} runs/s, "
                f"{speedup:.2f}x speedup, {efficiency:.1%} efficiency",
                flush=True,
            )


def build_parser() -> argparse.ArgumentParser:
    """Configure the campaign matrix and the test-only scheduling parameters."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=_worker_counts, default=_FULL_MATRIX)
    parser.add_argument("--runs", type=int, default=_FULL_RUNS)
    parser.add_argument("--backend", choices=_PROFILES, default="benchmark")
    parser.add_argument(
        "--out", type=Path, required=True, help="Parent directory for the evidence."
    )
    parser.add_argument("--seed", type=int, default=20261122)
    parser.add_argument("--batch", type=int, default=128)
    parser.add_argument("--inflight-factor", type=float, default=128)
    parser.add_argument("--tick", type=float, default=0.05)
    parser.add_argument("--sample-interval", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--startup-timeout", type=float, default=90)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run each worker count on a dedicated empty database and record the measurements."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if (
        min(
            args.runs,
            args.batch,
            args.inflight_factor,
            args.tick,
            args.sample_interval,
            args.timeout,
            args.startup_timeout,
        )
        <= 0
    ):
        parser.error("run count, batch, scheduling intervals and timeouts must be positive")
    if not os.environ.get("ROBOPROBE_DATABASE__URL"):
        parser.error("set ROBOPROBE_DATABASE__URL to a dedicated empty database")
    args.out.mkdir(parents=True, exist_ok=True)
    path = Path(mkdtemp(prefix="t130-", dir=args.out.resolve()))
    settings = load_settings(
        {
            "storage.artifact_root": str(path / "artifacts"),
            "storage.workdir_root": str(path / "workdirs"),
            "runner.max_batch_size": args.batch,
            "selection.benchmarks.function": "multi_mode_6d",
        }
    )
    engine = create_engine_from_settings(settings.database)
    measurements: list[Measurement] = []
    try:
        _require_empty_database(engine)
        upgrade_head(settings)
        for count in args.workers:
            trial = path / f"workers-{count}"
            trial.mkdir()
            measurements.append(_measure(settings, engine, args, trial, count))
            _record(measurements, path / "results.csv")
    finally:
        engine.dispose()
    if any(
        item.completed != args.runs
        or item.missing
        or item.duplicates
        or item.retries
        or item.participating_workers != item.workers
        for item in measurements
    ):
        return 1
    if args.workers == _FULL_MATRIX and args.runs >= _FULL_RUNS:
        return int(
            measurements[-1].runs_per_second / measurements[0].runs_per_second < _REQUIRED_SCALE
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
