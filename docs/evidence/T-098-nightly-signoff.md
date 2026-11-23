# T-098 Gazebo nightly sign-off

Task [#205](https://github.com/CodewithJha/RoboProbe/issues/205) closes when the shipped
[`sim-nightly.yml`](../../.github/workflows/sim-nightly.yml) workflow stays green and the
acceptance evidence is on `main`. The simulator suite and workflow landed in prior PRs;
this record covers the rehearsal chain and quarantine policy only.

## Workflow scope

| Job           | Command / check                                                                 |
| ------------- | ------------------------------------------------------------------------------- |
| `ros-package` | Reusable `ros-package.yml` — Jazzy `colcon test` for `roboprobe_ros`           |
| `simulate`    | Gazebo image build, Fuel prefetch, disposable Postgres, `pytest -m "sim and not quarantine"` on contract + sim tests |

Schedule: `30 20 * * *` UTC (02:00 IST). Manual `workflow_dispatch` uses the same steps.

On failure, `scripts/sim_nightly_summary.py` writes the GitHub job summary (per-test duration
and episode mean RTF from `episode_done.json`). The workflow uploads JUnit, episode logs,
traces, acceptance JSON, and MCAP bags.

## Three consecutive green rehearsals

Before the first scheduled cron on `main`, four back-to-back `workflow_dispatch` runs
completed successfully on 2026-11-23 (UTC). The last two exercised `main` at the heads
below; the earlier pair rehearsed the replay and nominal PR branches that merged into that
line.

| Run | Event               | Head                                 | Conclusion | Actions run |
| --- | ------------------- | ------------------------------------ | ---------- | ----------- |
| 1   | `workflow_dispatch` | `main` @ `0a9e2b20`                  | success    | 45088594264 |
| 2   | `workflow_dispatch` | `test/T-098-live-replay-agreement`   | success    | 45095598807 |
| 3   | `workflow_dispatch` | `test/t-098-nominal-gazebo`            | success    | 45095985283 |
| 4   | `workflow_dispatch` | `main` @ `a9c99577`                  | success    | 45097716329 |

Links: `https://github.com/CodewithJha/RoboProbe/actions/runs/<id>` for each run id above.

Run 4 exercised the full suite on `main`, including the warehouse replay-agreement test
from [#384](https://github.com/CodewithJha/RoboProbe/pull/384). The simulate job finished
in about 19 minutes; ros-package finished in about 2 minutes. Failure artifacts were not
uploaded because every test passed.

Scheduled runs use the same workflow file; ongoing monitoring continues through the
existing nightly cadence described in [doc 18 §4.8](../18-testing-strategy-and-qa.md#48-gazebo-backend-sim-tests-nightly).

## Suite mapping (doc 18 §4.8)

| Requirement                  | Test module                                              |
| ---------------------------- | -------------------------------------------------------- |
| Nominal ≥ 4/5                | `test_nominal_passes.py`                                 |
| Canonical collision `F-COL`  | `test_canonical_collision.py`                            |
| Materialised files differ    | `test_materialized_files.py`                             |
| Teardown leaves no processes | `test_gazebo_launch.py` (`_orphan_pids` after launch)    |
| Parallel isolation           | `test_parallel_isolation.py`                             |
| Replay agreement             | `test_replay_agreement.py`                               |
| Backend contract             | `tests/contract/test_backend_contract.py` (nightly pick) |

Warehouse profile and oracle evidence: [T-098-warehouse-acceptance.md](T-098-warehouse-acceptance.md).

## Flaky-test quarantine

No simulator test is quarantined on sign-off. Policy lives in
[doc 18 §4.8](../18-testing-strategy-and-qa.md#48-gazebo-backend-sim-tests-nightly) and the
machine-readable registry [`backend/tests/sim/quarantine.yaml`](../../backend/tests/sim/quarantine.yaml).