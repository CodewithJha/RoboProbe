# SC-5 kinematic2d replay evidence

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
30 seeds. Its S-PROBE mode inventory and release verdict are pending. [Issue #209](https://github.com/CodewithJha/RoboProbe/issues/209)

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
