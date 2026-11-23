# EXP-05 profile A vs profile B evidence (H6)

## Design and hypotheses

EXP-05 tests hypothesis **H6**: tuning the SUT profile using failure-mode insight raises the
**robustness score** (doc [09 §5.4](../../docs/09-failure-analysis-and-risk-mapping.md#54-volumes--robustness-score)).
Preregistered design:

| Config | Path | SHA-256 (file) |
|--------|------|----------------|
| PROBE on profile A / B | [exp05_profiles.yaml](../../configs/experiments/exp05_profiles.yaml) | `6523e113a32ddc58ebb4fcf72f09c5d94171418da9e59f2a33885b34e2c7b445` |
| Profile A (default Nav2) | [tb4_nav2_default.yaml](../../configs/sut_profiles/tb4_nav2_default.yaml) | — |
| Profile B (tuned) | [tb4_nav2_tuned.yaml](../../configs/sut_profiles/tb4_nav2_tuned.yaml) | `b54889db41befb01c1a9e2f4222f626d8a44c485540b4205d28d239cf4d2a8f5` |

Two `S-PROBE` arms (`profile_A`, `profile_B`), three seeds (`root: 20261119`), budget 80 → **6
campaigns**. Primary metrics: MET-06, MET-07 (`Δ = score_B − score_A` with bootstrap CI).

Profile B overrides are documented in the tuned YAML (k2d rule for F-COL: speed cap 0.38 m/s,
wider costmap inflation). Full Gazebo mode review from EXP-04 may refine them when
[#210](https://github.com/CodewithJha/RoboProbe/issues/210) compute lands.

This evidence uses the [`_experiment_template`](_experiment_template.md).

## Environment and reproduction

Requires PostgreSQL, orchestrator, and `worker-gazebo` (see [EXP-04](EXP-04.md) pre-flight).

```sh
make db-up migrate
docker compose -f docker/compose.yaml --profile core --profile gazebo up -d orchestrator worker-gazebo
roboprobe --json experiment run configs/experiments/exp05_profiles.yaml \
  --workers 1 --raw-parquet exp05_profiles.parquet > run.json
experiment_id=$(python3 -c 'import json; print(json.load(open("run.json"))["experiment_id"])')
roboprobe --json experiment report "$experiment_id" -o exp05_profiles.html
```

After each arm completes, run campaign analysis and record `robustness_score` plus Wilson CIs on
SAFE / UNCERTAIN / FAILURE volumes per profile.

## Results and interpretation (MET-07)

| Arm | `robustness_score` (point) | Wilson CI on volumes | Campaigns completed |
|-----|----------------------------|----------------------|---------------------|
| profile A (`tb4_nav2_default`) | *pending* | *pending* | 0 / 3 |
| profile B (`tb4_nav2_tuned`) | *pending* | *pending* | 0 / 3 |
| **MET-07 Δ (B − A)** | *pending* | bootstrap CI *pending* | — |

**H6 verdict:** **PENDING** — preregistered Gazebo matrix not executed on this repository record.

When data exist, state whether zero lies outside the MET-07 CI and note any new failure modes
introduced by profile B (trade-offs).

## Deviations and threats

| Item | Preregistered | This record |
|------|---------------|-------------|
| Seeds | 3 | Not run |
| Budget | 80 | Not run |
| Profile B rationale | From EXP-04 modes | Uses kinematic EXP-01 rule (doc 09 §4.3) until EXP-04 modes confirm |

See [deviations.md](deviations.md).

## Raw data and reports

| Artefact | Path | SHA-256 |
|----------|------|---------|
| Parquet | `exp05_profiles.parquet` | *after run* |
| HTML report | release asset if > 5 MB | *after run* |