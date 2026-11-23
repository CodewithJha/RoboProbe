# EXP-03 S-PROBE ablation evidence

## Design and hypotheses

EXP-03 tests H5: each S-PROBE ingredient contributes to discovery and time-to-failure.
Seven strategy variants (full PROBE plus ablations, plus `S-BO` and `S-LSE`) are compared
with Holm correction across variant pairs on MET-02 and MET-03.

| Item | Value |
|------|--------|
| Config | [exp03_ablation.yaml](../../configs/experiments/exp03_ablation.yaml) |
| SHA-256 (file) | `f7fbde08602a9d5fd765fc2f241619aa1b2e560ed926613a6968ac0373d5975e` |
| Variants | 7 |
| Seeds | 30 (root `20261119`) |
| Budget | 200 per campaign |
| Metrics | MET-02, MET-03, MET-09 |

This evidence uses the [`_experiment_template`](_experiment_template.md).

Ablations are parameter overrides of frozen S-PROBE defaults (T-061); see
`test_exp03_ablations_are_probe_param_overrides`.

## Environment and reproduction

```sh
roboprobe db upgrade
roboprobe --json experiment run configs/experiments/exp03_ablation.yaml \
  --workers 6 --raw-parquet exp03_ablation.parquet > run.json
experiment_id=$(python3 -c 'import json; print(json.load(open("run.json"))["experiment_id"])')
roboprobe --json experiment report "$experiment_id" -o exp03_ablation.html
```

Resume:

```sh
roboprobe --json experiment run configs/experiments/exp03_ablation.yaml \
  --resume "$experiment_id" --workers 6 \
  --raw-parquet exp03_ablation.parquet > run.json
```

The matrix plans **210 campaigns** (42 000 episodes). Schedule after or alongside
EXP-01 on the same compute lane (doc 19 §4).

## Results and interpretation

### Variant vs full PROBE (H5)

No preregistered EXP-03 campaign batch has completed in a single published Parquet
export on this repository record.

| Comparison | Primary metrics | Median / IQR | Â12 | Raw *p* | Holm *p* | Verdict |
|------------|-----------------|--------------|-----|---------|----------|---------|
| PROBE vs PROBE-diversity | MET-02, MET-03 | — | — | — | — | **INCOMPLETE** |
| PROBE vs PROBE-boundary | MET-02, MET-03 | — | — | — | — | **INCOMPLETE** |
| PROBE vs PROBE-refine | MET-02, MET-03 | — | — | — | — | **INCOMPLETE** |
| PROBE vs PROBE-eps0 | MET-02, MET-03 | — | — | — | — | **INCOMPLETE** |
| PROBE vs S-BO | MET-02, MET-03 | — | — | — | — | **INCOMPLETE** |
| PROBE vs S-LSE | MET-02, MET-03 | — | — | — | — | **INCOMPLETE** |

A **FAIL** on H5 means a full PROBE is not significantly better than an ablation after
Holm correction; that outcome will be stated explicitly when data are available.

## Deviations and threats

Same warehouse space and S-PROBE freeze as EXP-01. Construct validity of ablations
depends on weight renormalisation in the controller (doc 07 §6).

## Raw data and reports

| Artefact | Path | SHA-256 |
|----------|------|---------|
| Design (committed) | [exp03_ablation.yaml](../../configs/experiments/exp03_ablation.yaml) | `f7fbde08602a9d5fd765fc2f241619aa1b2e560ed926613a6968ac0373d5975e` |
| Raw Parquet | `exp03_ablation.parquet` | *pending* |
| HTML report | `exp03_ablation.html` | *pending* |

Files above 5 MB belong in a GitHub Release asset, not git.
