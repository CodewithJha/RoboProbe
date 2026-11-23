# EXP-06 Gazebo replay reproducibility evidence (SC-5 part 2)

## Design and hypotheses

EXP-06 measures **MET-06** — agreement between original Gazebo failure runs and deterministic
replays of EXP-04 mode medoids (doc [19 §4](../../docs/19-evaluation-and-experiment-plan.md#4-experiment-matrix)).
**SC-5** (Gazebo) requires MET-06 ≥ 0.8 with a Wilson confidence interval.

| Config | Path |
|--------|------|
| Replay plan | [exp06_gz_replay.yaml](../../configs/experiments/exp06_gz_replay.yaml) |

Each EXP-04 failure-mode medoid is replayed five times (`seeds.count: 5`, `budget: 1`). Medoid
run IDs are resolved from EXP-04 analysis outputs at experiment launch (not stored in git).

This evidence uses the [`_experiment_template`](_experiment_template.md).

## Environment and reproduction

Preconditions: EXP-04 campaigns analyzed and medoids exported; T-098 nightly green.

```sh
# Build medoids.csv with columns campaign_id,mode,medoid_run_id from EXP-04 analysis.
make db-up migrate
docker compose -f docker/compose.yaml --profile core --profile gazebo up -d orchestrator worker-gazebo
roboprobe --json experiment run configs/experiments/exp06_gz_replay.yaml \
  --workers 1 --raw-parquet exp06_replay.parquet > run.json
python3 scripts/replay_agreement.py medoids.csv --output exp06-replay.json
```

For each disagreement, compare manifests (`roboprobe runs diff-manifest a b`) and traces; follow
[RB-10](../../docs/30-operations-runbook.md#rb-10-replays-disagree-with-original-gazebo).

Repeat a subset with **fresh** seeds (not stored in the preregistered YAML) to separate
determinism from robustness; log in deviations if the protocol differs.

## Results and interpretation (MET-06)

| Field | Value |
|-------|-------|
| EXP-04 medoids eligible | *pending* (EXP-04 matrix not completed) |
| Replays executed | 0 |
| Disagreements | — |
| **MET-06** | *pending* |
| Wilson 95 % CI | *pending* |
| **SC-5 (Gazebo)** | **PENDING** |

Kinematic counterpart (MET-06 = 1.0 on measured EXP-01 cohort): [SC-5-k2d.md](SC-5-k2d.md).

### Disagreement causes (RB-10)

No new causes beyond [RB-10](../../docs/30-operations-runbook.md#rb-10-replays-disagree-with-original-gazebo)
recorded in this pass. When replays run, add rows here for `/clock` jitter, DDS drops, RTF collapse,
or image digest drift.

## Deviations and threats

| Item | Preregistered | This record |
|------|---------------|-------------|
| Medoid set | From completed EXP-04 | EXP-04 preregistered matrix pending |
| Replays per medoid | 5 | Not run |

See [deviations.md](deviations.md).

## Raw data and reports

| Artefact | Status |
|----------|--------|
| `exp06_replay.parquet` | Pending |
| `exp06-replay.json` | Pending |
| Medoids CSV | Pending EXP-04 analysis export |
