# EXP-07 dimension and noise scalability evidence

## Design and hypotheses

EXP-07 tests whether S-PROBE retains discovery and time-to-failure advantages as the
warehouse space gains dimensions or lidar noise increases. The preregistered design has
three kinematic2d arms (RANDOM vs PROBE, 30 seeds, budget 300 each):

| Arm | Config | SHA-256 |
|-----|--------|---------|
| d = 6 baseline | [exp07_scalability.yaml](../../configs/experiments/exp07_scalability.yaml) | `fe36d7f77877982384d089b94b2490cc1b7da759ad58eefe56862f2c0428dba6` |
| d = 8 | [exp07_scalability_d8.yaml](../../configs/experiments/exp07_scalability_d8.yaml) | `da57986f777b3bc357e8c07556858e3950b5d50752a40e18ddf8bd2432779154` |
| Lidar noise ×2 | [exp07_scalability_noise2.yaml](../../configs/experiments/exp07_scalability_noise2.yaml) | `f06ec9280c64e310073bb844a8428c5fbfabd0ad622ee45de6a8b93e25c557d6` |

Primary metrics: MET-02, MET-03, MET-09. α = 0.05 with Holm correction across the two
strategies per arm.

This evidence uses the [`_experiment_template`](_experiment_template.md).

### Pipeline smoke design (d = 6)

A reduced design mirrors the d = 6 arm for local pipeline checks:

The [pilot design](exp07-pilot/design.yaml) has SHA-256
`81fbcf72602d459ae9005f265e16baaa9fbf2121c737e4ad84bcfbb325978d7e`.
It uses one seed, two strategies, and budget 16.

## Environment and reproduction

### Preregistered runs (comparative result pending)

```sh
roboprobe db upgrade
for cfg in configs/experiments/exp07_scalability.yaml \
           configs/experiments/exp07_scalability_d8.yaml \
           configs/experiments/exp07_scalability_noise2.yaml; do
  roboprobe --json experiment run "$cfg" --workers 6 \
    --raw-parquet "$(basename "$cfg" .yaml).parquet" > run.json
  experiment_id=$(python3 -c 'import json; print(json.load(open("run.json"))["experiment_id"])')
  roboprobe --json experiment report "$experiment_id" -o "$(basename "$cfg" .yaml).html"
done
```

### Pipeline smoke (d = 6, reduced)

```sh
roboprobe db upgrade
roboprobe --json experiment run docs/evidence/exp07-pilot/design.yaml \
  --workers 2 --raw-parquet docs/evidence/exp07-pilot/runs.parquet > run.json
experiment_id=$(python3 -c 'import json; print(json.load(open("run.json"))["experiment_id"])')
roboprobe --json experiment report "$experiment_id" -o exp07_smoke.html
```

Kinematic2d experiments require PostgreSQL and the standard backend worker extra.
Related kinematic campaign evidence: [SC-5 kinematic2d replay](SC-5-k2d.md).

## Results and interpretation

### Preregistered arms

No preregistered EXP-07 arm has completed on this repository record. Comparative
tables (median/IQR, p, p_Holm, Â12) are **pending** for all three arms.

### Pipeline smoke

The committed smoke design is ready for execution; Parquet and HTML hashes will be
recorded in this section when the owner runs the commands above on a fresh database
(next to [exp07-pilot/design.yaml](exp07-pilot/design.yaml)).

Until then, kinematic2d experiment persistence is supported by the SC-5 replay pilot
and the integration tests cited in [doc 28](../../docs/28-traceability-matrix.md)
for FR-EXP-001.

## Deviations and threats

| Item | Preregistered | This record |
|------|---------------|-------------|
| Seeds | 30 per arm | Smoke design uses 1 (not yet executed) |
| Budget | 300 | Smoke design uses 16 |
| Arms | 3 | Full runs not completed |
| Strategies | 2 | Same |

See [deviations.md](deviations.md).

## Raw data and reports

| Artefact | Status |
|----------|--------|
| Preregistered Parquet / HTML (×3) | Pending full runs |
| Smoke Parquet | Pending owner execution of smoke commands |
| Files > 5 MB | GitHub Release asset (not git) |
