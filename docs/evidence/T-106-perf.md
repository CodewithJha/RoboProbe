# T-106 API performance evidence

The benchmark verifies [NFR-PERF-004](../02-software-requirements-specification.md) against
one completed analytic benchmark campaign. The seed contained 10,000 `DONE` runs, including
9,902 `PASS` and 98 `FAIL` results. Seed generation took 303.72 seconds.

## Observed load test

On 2026-11-22, Locust 2.47.0 on Python 3.12.13 sent requests to RoboProbe revision
`f6c36fa` on loopback. The client and API ran on macOS 26.5.2 (`arm64`) and the local Docker
service ran PostgreSQL 17.12. Locust ran for 60 seconds with 20 users, spawning 5 users per second.
The table comes from the complete CSV written after the runner stopped.

| Endpoint | Requests | Failures | p95 (ms) | Budget (ms) |
|---|---:|---:|---:|---:|
| `GET /api/v1/campaigns` | 404 | 0 | 19 | 200 |
| `GET /api/v1/campaigns/{id}/runs` | 4,543 | 0 | 18 | 200 |
| `GET /api/v1/runs/{id}` | 368 | 0 | 13 | 200 |
| `GET /api/v1/campaigns/{id}/modes` | 202 | 0 | 13 | 200 |

The test completed 5,517 requests at 92.0 requests per second. An earlier run on `a8d1e9c`
completed 5,102 requests with zero failures and p95 between 84 and 120 ms across the four groups.
The benchmark campaign has an empty mode list, so the modes measurement covers the endpoint
and its database query.

The workload weights campaign listing, run browsing, run details and mode listing 2:5:2:1.
Browsing follows five cursor pages of ten runs. It rotates between descending ordinal, ascending
robustness for completed passes, and descending finish time for failures. The checker rejects
failed requests, empty groups and p95 breaches. Applying a temporary 1 ms campaign-list budget
to a real run printed `p95 above limit` and returned exit status 1.

## PostgreSQL query plan

The [plan script](../../backend/tests/perf/explain_runs.sql) runs `EXPLAIN (ANALYZE, BUFFERS)`
for the fifth page of `GET /campaigns/{id}/runs?limit=10&sort=-ordinal`. It uses the same
`(ordinal, id)` boundary and fetches 11 rows so the API can determine whether another page exists.

```text
Limit  (cost=0.67..5.24 rows=11 width=759) (actual time=0.021..0.023 rows=11 loops=1)
  Buffers: shared hit=13
  ->  Incremental Sort  (cost=0.67..4145.95 rows=9960 width=759) (actual time=0.021..0.021 rows=11 loops=1)
        Sort Key: ordinal DESC, id DESC
        Presorted Key: ordinal
        Full-sort Groups: 1  Sort Method: quicksort  Average Memory: 36kB  Peak Memory: 36kB
        Buffers: shared hit=13
        ->  Index Scan Backward using uq_runs_campaign_id on runs  (cost=0.29..3697.75 rows=9960 width=759) (actual time=0.008..0.014 rows=12 loops=1)
              Index Cond: ((campaign_id = '01a1ee56-5e00-7000-8000-000000000000'::uuid) AND (ordinal <= 9960))
              Filter: (ROW(ordinal, id) < ROW(9960, '01a1ee56-5e07-7331-b44c-a0afd2ff2f05'::uuid))
              Rows Removed by Filter: 1
              Buffers: shared hit=13
Planning:
  Buffers: shared hit=102
Planning Time: 0.143 ms
Execution Time: 0.040 ms
```

## Reproduction

Run the [API performance workflow](../../.github/workflows/api-perf.yml) with a fresh PostgreSQL 17
service, or follow the same steps against a disposable local database. The seed command rejects
databases with existing application data.

1. Run `uv run --directory backend --locked python ../scripts/seed_demo.py --size large`
   with `--database-url`, `--workdir-root` and `--artifact-root` for the scratch database.
2. Set `ROBOPROBE_PERF_CAMPAIGN_ID` to the seeded campaign ID. Run `psql` against that database
   with `-v ON_ERROR_STOP=1 -v campaign_id="$ROBOPROBE_PERF_CAMPAIGN_ID"`
   and `-f backend/tests/perf/explain_runs.sql`.
3. Start `uv run --directory backend --locked roboprobe api` on loopback with the matching
   `ROBOPROBE_DATABASE__URL` and storage roots. Wait for `/health/ready` to return 200.
4. Run the following commands from the repository root. Adjust the loopback port if needed.

   ```bash
   uvx --python 3.12 locust==2.47.0 --headless -u 20 -r 5 -t 60s --only-summary \
     --host http://127.0.0.1:8000 -f backend/tests/perf/locustfile.py --csv perf
   mv perf_complete_stats.csv perf_stats.csv
   uv run --directory backend --locked python tests/perf/check_stats.py ../perf_stats.csv
   ```

The workflow uploads the complete stats, history, failures, exceptions, API log, seed log and
query plan as the `api-performance` artifact. Its budgets are in
[thresholds.toml](../../backend/tests/perf/thresholds.toml).
