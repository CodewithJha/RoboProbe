# EXP-04 Gazebo evidence (SC-4)

## Design and hypotheses

EXP-04 is the real-stack comparison for H1–H3 on the six-dimensional `warehouse_v1`
space with the TB4 Nav2 profile. Preregistered design:

| Config | Path | SHA-256 (file) |
|--------|------|----------------|
| RANDOM vs PROBE | [exp04_gazebo.yaml](../../configs/experiments/exp04_gazebo.yaml) | `1e5b74000d42ae4b2be121d5d94aec31e55c97c915e1733e110f07129fb34d7a` |

Two strategies (S-RANDOM, S-PROBE), five seeds (`root: 20261119`), budget 80 → **10
campaigns**. Primary metric MET-03; MET-01, MET-02 recorded. Doc 19's one-off OFAT arm
(30 runs) is **not** in this schema-v1 file — track any OFAT run separately in
[deviations.md](deviations.md).

H3 and **SC-4** require at least one **confirmed interaction failure mode** on Gazebo
(doc [19 §6](../../docs/19-evaluation-and-experiment-plan.md#6-success-thresholds-link-to-01-7),
[01 §7](../../docs/01-vision-and-product-brief.md#7-success-criteria-project-level-acceptance)).
Kinematic evidence from EXP-01 ([#208](https://github.com/CodewithJha/RoboProbe/issues/208))
is **not** a prerequisite for scheduling EXP-04; comparisons here are scoped to this
experiment only.

This evidence uses the [`_experiment_template`](_experiment_template.md).

### Pipeline smoke (reduced)

The [pilot design](exp04-pilot/design.yaml) uses one seed, two strategies, budget 4 (two
campaign cells). File SHA-256:
`9f4a6f3892048e6d041b1c9c4aea925ddad49819e0493e500f7252af0c2a9cf1`.

## Pre-flight

Complete before starting the ≈22 h campaign matrix (doc 19 §4):

1. [T-098 nightly sign-off](T-098-nightly-signoff.md) green on `main` ([#205](https://github.com/CodewithJha/RoboProbe/issues/205) closed).
2. `make gz-build` and Fuel prefetch per [doc 17 §5](../../docs/17-dev-environment-and-docker.md#5-images).
3. Compose `core` + `gazebo` profiles; set
   `ROBOPROBE_BACKENDS__GAZEBO_NAV2__MAX_PARALLEL_PER_HOST` to what the host sustains
   (see [RB-02](../../docs/30-operations-runbook.md#rb-02-gazebo-episodes-slow-rtf--05)).
4. `make backup`; confirm disk headroom for MCAP bags.
5. Monitor dashboard/SSE during long runs; on auto-pause see
   [RB-01](../../docs/30-operations-runbook.md#rb-01-campaign-auto-paused-with-infra_unhealthy),
   [RB-03](../../docs/30-operations-runbook.md#rb-03-nav2-never-becomes-active),
   [RB-04](../../docs/30-operations-runbook.md#rb-04-orphan-gzros2-processes-memory-climbing).

## Environment and reproduction

### Preregistered run (comparative result pending)

Requires PostgreSQL, orchestrator, and `worker-gazebo` (or equivalent remote workers).

```sh
make db-up migrate
docker compose -f docker/compose.yaml --profile core --profile gazebo up -d orchestrator worker-gazebo
roboprobe --json experiment run configs/experiments/exp04_gazebo.yaml \
  --workers 1 --raw-parquet exp04_gazebo.parquet > run.json
experiment_id=$(python3 -c 'import json; print(json.load(open("run.json"))["experiment_id"])')
roboprobe --json experiment report "$experiment_id" -o exp04_gazebo.html
```

After campaigns finish, run analysis on each campaign with failures, then confirm
interactions on top modes (`POST /api/v1/modes/{mode_id}:confirm-interaction` or
Casebook **Confirm interaction**). Pick one SC-4 showcase mode (medoid run id).

### Pipeline smoke (reduced)

```sh
make db-up migrate
docker compose -f docker/compose.yaml --profile core --profile gazebo up -d orchestrator worker-gazebo
roboprobe --json experiment run docs/evidence/exp04-pilot/design.yaml \
  --workers 1 --raw-parquet docs/evidence/exp04-pilot/runs.parquet > run.json
experiment_id=$(python3 -c 'import json; print(json.load(open("run.json"))["experiment_id"])')
roboprobe --json experiment report "$experiment_id" -o exp04_smoke.html
```

Record wall time, worker image digest, and mean episode RTF from run artefacts when executed.

## SC-4 verdict

| Criterion | Preregistered threshold | This record |
|-----------|-------------------------|-------------|
| SC-4 | ≥ 1 confirmed **interaction** failure mode on Gazebo | **PENDING** — preregistered campaigns not completed on this repository record |

When a mode is confirmed, fill the table below and attach demo assets (not in git if > 5 MB).

### Interaction failure case (to complete after run)

| Field | Value |
|-------|-------|
| Mode id | *pending* |
| Medoid run id | *pending* |
| Parameters (interaction) | *pending* |
| Confirm-interaction campaign | *pending* |
| Demo video (release asset) | *pending — ≤ 2 min Gazebo GUI replay per doc 17 §6* |
| MCAP / bag (release asset) | *pending* |
| `make gz-debug RUN=<id>` notes | *optional* |

## Results and interpretation

### Preregistered matrix

No EXP-04 preregistered cell has completed on this repository record. Median/IQR
comparisons for MET-03, mode counts (MET-02), Holm-adjusted p-values, and Â12 for H1–H2
are **pending**.

### Pipeline smoke

The committed smoke design is ready for execution; Parquet and HTML hashes will be
recorded here when the owner runs the smoke commands on a Gazebo-capable host.

## Deviations and threats

| Item | Preregistered | This record |
|------|---------------|-------------|
| Seeds | 5 | Smoke uses 1 (not yet executed) |
| Budget | 80 | Smoke uses 4 |
| OFAT arm (doc 19) | once, 30 runs | Not in `exp04_gazebo.yaml` (schema v1) — log separately if run |
| EXP-01 k2d stats ([#208](https://github.com/CodewithJha/RoboProbe/issues/208)) | informs paper narrative | Not required to **start** EXP-04; Gazebo claims stand on this experiment |

See [deviations.md](deviations.md).

## Raw data and reports

| Artefact | Path | SHA-256 |
|----------|------|---------|
| Pilot design | [exp04-pilot/design.yaml](exp04-pilot/design.yaml) | `9f4a6f3892048e6d041b1c9c4aea925ddad49819e0493e500f7252af0c2a9cf1` |
| Pilot Parquet | `exp04-pilot/runs.parquet` | *after smoke run* |
| Preregistered Parquet | `exp04_gazebo.parquet` | *after full run* |
| HTML reports | release asset if > 5 MB | *after runs* |