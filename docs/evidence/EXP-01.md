# EXP-01 kinematic2d main comparison evidence

## Design and hypotheses

EXP-01 tests H1–H4 on the warehouse kinematic2d space: sims-to-first-failure (MET-03),
distinct failure modes (MET-02, MET-09), interaction discovery, and risk-map accuracy (MET-08).

| Item | Value |
|------|--------|
| Config | [exp01_k2d_main.yaml](../../configs/experiments/exp01_k2d_main.yaml) |
| SHA-256 (file) | `3f05a959da30ca944f8dfe2ef561dfb7ab64f9b1bf7a9136b4cd94cfc46f1afd` |
| Strategies | 8 (`S-RANDOM` … `S-PROBE`) |
| Seeds | 30 (root `20261119`) |
| Budget | 200 per campaign |
| Primary metric | MET-03 (α = 0.05, Holm across strategy pairs) |

This evidence uses the [`_experiment_template`](_experiment_template.md).

Reference-set mode matching for MET-02 and SC-3 uses [T-103](T-103-reference-set.md)
(`experiments.reference_set.*`, `experiments.mode_match_radius`).

## Environment and reproduction

### Preregistered run

Requires PostgreSQL, artifact store, and kinematic2d workers (doc 17).

```sh
roboprobe db upgrade
roboprobe --json experiment run configs/experiments/exp01_k2d_main.yaml \
  --workers 6 --raw-parquet exp01_k2d_main.parquet > run.json
experiment_id=$(python3 -c 'import json; print(json.load(open("run.json"))["experiment_id"])')
roboprobe --json experiment report "$experiment_id" -o exp01_k2d_main.html
```

Resume after interruption:

```sh
roboprobe --json experiment run configs/experiments/exp01_k2d_main.yaml \
  --resume "$experiment_id" --workers 6 \
  --raw-parquet exp01_k2d_main.parquet > run.json
```

Partial replay and MET-06 checks for completed S-PROBE campaigns: [SC-5 kinematic2d](SC-5-k2d.md).

## Results and interpretation

### Preregistered matrix (SC-1 … SC-3)

The design plans **240 campaigns** (48 000 k2d episodes). As of this record the
orchestrator has been exercised on the owner compute lane ([#389](https://github.com/CodewithJha/RoboProbe/pull/389));
the full matrix is **not** complete in a single exportable Parquet artifact yet.

| Criterion | Threshold (doc 01 §7) | Recorded value | Holm *p* / Â12 / CI | Verdict |
|-----------|------------------------|----------------|---------------------|---------|
| **SC-1** | MET-03 median(`S-PROBE`) ≤ 0.5 × median(`S-RANDOM`); MWU *p* < 0.05 | — | — | **INCOMPLETE** |
| **SC-2** | Â12(`S-PROBE`, `S-RANDOM`) on MET-02 ≥ 0.64 | — | — | **INCOMPLETE** |
| **SC-3** | GT-A found in ≥ 90 % of `S-PROBE` seeds within budget 200 | — | Wilson CI — | **INCOMPLETE** |

Verdicts stay **INCOMPLETE** until all 240 campaigns finish and statistics are computed
with the reference set (T-103). Negative results will be reported at the same thresholds
(doc 19 §5).

### Supporting evidence (not sufficient for SC-1…3)

Five completed preregistered `S-PROBE` campaigns (200 episodes each) achieved
**MET-06 = 1.0** on medoid replay; see [SC-5-k2d.md](SC-5-k2d.md) and
[SC-5-k2d-exp01-first-five.csv](SC-5-k2d-exp01-first-five.csv).

## Deviations and threats

Full-scale timing and worker count follow the owner environment. No post-T-061
hyper-parameter changes. Deviations from the preregistered scale are logged in
[deviations.md](deviations.md) when they occur.

## Raw data and reports

| Artefact | Path | SHA-256 |
|----------|------|---------|
| Design (committed) | [exp01_k2d_main.yaml](../../configs/experiments/exp01_k2d_main.yaml) | `3f05a959da30ca944f8dfe2ef561dfb7ab64f9b1bf7a9136b4cd94cfc46f1afd` |
| Raw Parquet (full run) | `exp01_k2d_main.parquet` | *pending full completion* |
| HTML report | `exp01_k2d_main.html` | *pending* |

Files above 5 MB belong in a GitHub Release asset, not git.
