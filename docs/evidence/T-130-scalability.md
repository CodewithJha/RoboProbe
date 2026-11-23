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

## Isolated Ubuntu comparisons

Each GitHub-hosted Ubuntu 24.04 VM ran the same full benchmark command and kept its
PostgreSQL 17 service on that VM. Each matrix completed 40,000 episodes. Every configured
worker finished runs, and all matrices recorded zero missing ordinals, duplicate ordinals,
and retries. All three performance gates returned status 1 because the speedup was below 6×.
Use the speedup within each VM when comparing worker levels.

| Candidate | 1 worker runs/s | 2 worker runs/s | 4 worker runs/s | 8 worker runs/s | 8 worker speedup | 8 worker efficiency |
|-----------|----------------:|----------------:|----------------:|----------------:|-----------------:|--------------------:|
| Main baseline | 30.48 | 33.81 | 32.82 | 30.65 | 1.01× | 12.6% |
| Vectorized selector | 54.66 | 62.78 | 62.11 | 58.86 | 1.08× | 13.5% |
| Selector and campaign snapshots | 62.17 | 108.65 | 124.50 | 140.65 | 2.26× | 28.3% |

The checked-in CSVs preserve the hosted values with Unix line endings. Each workflow
archive contains the original CSV, child process logs, campaign configurations, and a
SHA-256 manifest. All 26 files in each archive were checked against its manifest.

| CSV | Product commit | Archive CSV SHA-256 | Archived run |
|-----|----------------|-------------|--------------|
| [Baseline](T-130-scalability-ubuntu-baseline.csv) | `52191f1` | `3d57aacce0e7e576cf972b7e913ad762fa9ecbae09616ad55c856e34e220b1cb` | [Baseline logs](https://github.com/CodewithJha/RoboProbe/actions/runs/45101430830) |
| [Selector](T-130-scalability-ubuntu-selector.csv) | `8c2fe45` | `43763e22db0151dc01bfa406a41d9bb6eda52711d30a2a837ea9355329aa90a7` | [Selector logs](https://github.com/CodewithJha/RoboProbe/actions/runs/45101959515) |
| [Combined](T-130-scalability-ubuntu-combined.csv) | `1b71a83` | `be077f88b55cbe0a5b50afbde6a1f96c76b47a018730119d0bca6e06ec076d32` | [Combined logs and runner tests](https://github.com/CodewithJha/RoboProbe/actions/runs/45102816562) |

| Eight-worker measurement | Baseline | Selector | Combined |
|--------------------------|---------:|---------:|---------:|
| Completed episodes per worker | 1,238–1,260 | 1,227–1,285 | 1,236–1,269 |
| Mean worker CPU in occupied cores | 0.66 | 0.85 | 2.34 |
| Mean orchestrator CPU in occupied cores | 0.80 | 0.70 | 0.51 |
| Median gap between the final eight proposal pairs (s) | 6.984 | 3.434 | 0.765 |
| PostgreSQL activity polls | 646 | 337 | 140 |
| `LWLock:WALWrite` samples | 115 | 51 | 5 |
| `Lock:object` samples | 56 | 24 | 2 |

At eight workers, the combined candidate averaged about 0.29 occupied CPU cores per
worker and 0.51 cores in the orchestrator. PostgreSQL runs in a separate service and
its CPU is outside those sums. Samples of WAL and object-lock waits were rarer per poll
with the combined code. Proposal intervals include all work between proposal log entries.

GitHub specifies four vCPUs for standard public Ubuntu VMs. A separate probe confirmed
four available CPUs and affinity `0-3` for both the x64 and arm64 labels. The three
benchmark archives record their runner image versions. A shallow checkout interrupted
the host-metadata step after it printed the commit, leaving exact per-run affinity unverified.
The baseline and selector ran on image `20261116.376.1`. The combined candidate
ran on `20261116.133.1`. The prior Mac matrix shared its host with development tests.
[GitHub runner specifications](https://docs.github.com/en/actions/reference/runners/github-hosted-runners#standard-github-hosted-runners-for-public-repositories)
· [Capacity probe](https://github.com/CodewithJha/RoboProbe/actions/runs/45103679584)

For the next capacity test, run the same full matrix from the combined code on an
isolated Linux machine with 12 available CPUs. At the observed combined eight-worker
cost, 6× the one-worker rate would use about 7.6 cores for workers and the orchestrator
before PostgreSQL. Record
`nproc` and `Cpus_allowed_list`, and sample PostgreSQL container CPU and block I/O once
per second with `docker stats`. Snapshot `SELECT * FROM pg_stat_wal` and
`SHOW synchronous_commit`, `SHOW fsync`, and `SHOW full_page_writes` before and after
the benchmark. Preserve the same PostgreSQL major version and durability settings.
Compare WAL and object-lock observations per poll and database CPU at one and eight
workers. This will show whether disk or lock contention becomes more frequent as more
worker CPU is available.
