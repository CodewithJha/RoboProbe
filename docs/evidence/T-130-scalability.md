# T-130 campaign scalability

## Reproduce the workload

Start a dedicated empty PostgreSQL database and set `ROBOPROBE_DATABASE__URL` for it in a local
shell. The command refuses a database with any application data. Run from a RoboProbe checkout
with the standard backend environment and worker extra installed.

```sh
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
uv run --directory backend python ../scripts/load_campaign.py \
  --workers 1,2,4,8 --runs 10000 --backend benchmark --out /tmp/roboprobe-t130
```

Each worker count gets its own S-RANDOM campaign with the same seed, scenario space, and run
budget. The harness starts separate `roboprobe worker` processes and a normal orchestrator. It
waits for the workers to register before starting the campaign and stops the test processes
after each trial. Use `ROBOPROBE_WORKER__HEALTH_PORT` to select an unused orchestrator probe port.
The result directory contains the CSV, child process logs, campaign configs, and run artifacts.

Wall time includes campaign creation and ends when the observer sees the completed status.
Throughput is completed runs divided by that wall time. Speedup divides each rate by the
one-worker rate. Efficiency divides speedup by the worker count. Claim latency comes from
PostgreSQL's `claimed_at - enqueued_at` timestamps. Connection and dead-tuple peaks are sampled
estimates. PostgreSQL's dead-tuple estimates change as autovacuum runs, so the CSV records
the baseline, high-water estimate, and ending estimate for every trial.

The script checks each expected run ordinal, duplicate ordinals, retried claims, and actual
worker participation. The full four-level matrix also requires at least 6× throughput at
eight workers.

New measurements also include combined worker CPU seconds, orchestrator CPU seconds, and
the number of PostgreSQL activity observations. The CSV's `active_db_wait_samples` column
is a JSON object keyed by PostgreSQL wait event. Each poll counts active client sessions in
the test database, excluding the observer. A session with no reported wait may be running
or ready to run. Sample counts describe observations of activity and do not measure
cumulative time spent waiting.

## Pilot measurements

The local pilot used PostgreSQL 17 in Docker Desktop on an Apple Silicon Mac with 150
`benchmark` episodes per worker count. A shared host was in use. These results validate the
measurement path and worker participation.

| Workers | Completed | Runs/s | Speedup | Efficiency | Claim p95 (ms) | Peak connections | Peak dead tuples |
|---------|-----------|--------|---------|------------|----------------|------------------|------------------|
| 1 | 150 | 5.37 | 1.00× | 100.0% | 19,888 | 5 | 900 |
| 2 | 150 | 7.02 | 1.31× | 65.4% | 17,763 | 7 | 1,314 |
| 4 | 150 | 17.70 | 3.30× | 82.5% | 6,603 | 11 | 1,498 |
| 8 | 150 | 33.78 | 6.30× | 78.7% | 2,930 | 11 | 2,168 |

All 600 expected runs completed with zero missing ordinals, duplicate ordinals, and retries.
Every worker claimed at least one completed run. The [pilot CSV](T-130-scalability-pilot.csv)
includes the additional timing and database measurements. The 10,000-run matrix is required
to evaluate the scalability acceptance criterion.

## Full 10,000-run matrix

Run on 2026-11-23 IST with PostgreSQL 17 in Docker Desktop on a shared Apple Silicon Mac.
The database VM had 10 virtual CPUs and approximately 7.75 GiB of RAM. The backend workers
ran on the host. The workload was the same seeded analytical benchmark in each arm, with
10,000 runs per arm. The isolated database began empty; the four campaigns ran sequentially.
Other development tests ran on the host during this measurement.

| Workers | Completed | Runs/s | Speedup | Efficiency | Claim p50 (ms) | Claim p95 (ms) | Peak connections | Peak dead tuples |
|---------|-----------|--------|---------|------------|----------------|----------------|------------------|------------------|
| 1 | 10,000 | 8.77 | 1.00× | 100.0% | 9,401 | 49,292 | 5 | 60,006 |
| 2 | 10,000 | 14.62 | 1.67× | 83.4% | 7,558 | 27,656 | 7 | 59,989 |
| 4 | 10,000 | 23.52 | 2.68× | 67.1% | 3,393 | 82,360 | 11 | 59,991 |
| 8 | 10,000 | 33.08 | 3.77× | 47.2% | 2,184 | 7,799 | 19 | 64,545 |

Every configured worker finished runs. The database recorded zero missing runs, duplicate
ordinals, and retries across 40,000 completed runs. The [full CSV](T-130-scalability-full.csv)
includes unrounded measurements and per-arm baseline and ending dead-tuple estimates.

Eight workers achieved 3.77× the one-worker throughput. The full matrix exited with status 1
because the performance gate requires at least 6×. The claim-latency tail also increased at
four workers. The cause of the nonlinear scaling remains unconfirmed. A dedicated-host rerun with worker
CPU and PostgreSQL wait-event measurements can show where available capacity is spent.
