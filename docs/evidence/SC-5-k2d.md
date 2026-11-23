# SC-5 kinematic2d replay evidence

## Verdict (SC-5 kinematic2d)

| Field | Value |
|-------|-------|
| Criterion | SC-5 — MET-06 = 1.0 on kinematic2d (doc 01 §7) |
| Campaigns replayed | 6 (`S-PROBE`: 1 pilot + 5 preregistered EXP-01 seeds) |
| Mode medoids | 29 unique modes (8 pilot + 21 from the five-seed snapshot) |
| Replays | 145 (`5` per medoid) |
| Disagreements | 0 |
| **MET-06** | **1.0** |
| **SC-5 (k2d)** | **PASS** |

Remaining preregistered EXP-01 `S-PROBE` seeds (blocked by [#208](https://github.com/CodewithJha/RoboProbe/issues/208))
use the batch workflow below; any future disagreement is a reproducibility bug (doc 18 §7).

## S-PROBE pilot

The pilot ran 80 episodes in a single S-PROBE warehouse campaign using the first
seed from the EXP-01 design. PostgreSQL recorded 21 passing and 59 failing runs.
The normal HDBSCAN settings produced eight medoids. Incremental analysis used
256 points for its separate risk-volume estimate.

Each medoid was replayed five times with its original seed in an isolated database.
All 40 replays matched the original verdict and primary failure. All 40 trace
hashes also matched. Pilot MET-06 was **1.0**.

| Mode | Original failure | Matching verdict and class | Matching trace |
|------|------------------|----------------------------|----------------|
| FM-01 | F-LOC | 5/5 | 5/5 |
| FM-02 | F-TIMEOUT | 5/5 | 5/5 |
| FM-03 | F-STUCK | 5/5 | 5/5 |
| FM-04 | F-STUCK | 5/5 | 5/5 |
| FM-05 | F-STUCK | 5/5 | 5/5 |
| FM-06 | F-STUCK | 5/5 | 5/5 |
| FM-07 | F-STUCK | 5/5 | 5/5 |
| FM-08 | F-STUCK | 5/5 | 5/5 |

The [full EXP-01 design](../../configs/experiments/exp01_k2d_main.yaml) uses
30 seeds; five had completed and been analyzed when the snapshot below was taken.

## First five completed EXP-01 campaigns

An isolated PostgreSQL snapshot captured five completed S-PROBE campaigns from
the full [preregistered EXP-01 design](../../configs/experiments/exp01_k2d_main.yaml).
Each of those campaigns ran the original 200-episode budget. Full failure-mode
analysis found 21 medoids across them. Each medoid was replayed five times with
the original seed. All 105 replays matched the source verdict, primary failure,
and trace hash. Each of the five campaigns measured **MET-06 = 1.0**.

The [per-mode evidence](SC-5-k2d-exp01-first-five.csv) includes the source run
IDs and match counts. The snapshot includes the five campaigns completed when
it was taken. Additional seeds are collected under [#208](https://github.com/CodewithJha/RoboProbe/issues/208).

## Run the replay batch

Export one CSV row per stored failure mode from the completed S-PROBE campaigns.
The CSV columns are `campaign_id,mode,medoid_run_id`. Use `failure_modes.code`
as the mode value and `failure_modes.medoid_run_id` for the source run. Use the
same database and artifact store as the source campaign.

```sh
python3 scripts/replay_agreement.py medoids.csv --output sc5-replay.json
```

The JSON stores the replay IDs and verdict comparisons. It also records completion
counts and the mean mode agreement for each campaign. A complete batch with any
disagreement exits with status 3. Inspect the source and replay manifests and
trace digests for each disagreement before filing its reproducibility bug.
