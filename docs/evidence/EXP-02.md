# EXP-02 analytic evidence

## Design and hypotheses

EXP-02 supports H1 and H2 on analytic benchmarks before the kinematic and Gazebo
comparisons. The preregistered design has two arms:

| Arm | Config | SHA-256 |
|-----|--------|---------|
| `multi_mode_6d` | [exp02_analytic.yaml](../../configs/experiments/exp02_analytic.yaml) | `5f5c0b1625395096a4d066ce6d0bcfb447ee645ff52d2c6fc86a397cc5b47f6b` |
| `branin_falsify` | [exp02_branin.yaml](../../configs/experiments/exp02_branin.yaml) | `8a33d0c2e6e17e7ae709d059ba3c234ea60b01ca4a92bc0b60ac347aa5b77ac3` |

Each arm uses eight strategies, 50 seeds, budget 150, primary metric MET-03, and
α = 0.05 with Holm correction across strategy pairs. Metrics MET-01, MET-02, MET-03,
and MET-09 are recorded.

This evidence uses the [`_experiment_template`](_experiment_template.md).

### Pipeline pilot (multi_mode_6d arm)

The recorded pilot checks persistence, Parquet export, and HTML reporting on a
reduced design that keeps the EXP-02 seed root and space. Experiment ID:
`542da849-08a5-4a17-9379-e1944775078e`.

The [pilot design](exp02-pilot/design.yaml) has SHA-256
`435a2ae303462a683e0e267d26832e34da1294cbaabf8f3f77fcf6ed25b9dada`.

## Environment and reproduction

### Preregistered run (comparative result pending)

```sh
roboprobe db upgrade
roboprobe --json experiment run configs/experiments/exp02_analytic.yaml \
  --workers 6 --raw-parquet exp02_analytic.parquet > run.json
experiment_id=$(python3 -c 'import json; print(json.load(open("run.json"))["experiment_id"])')
roboprobe --json experiment report "$experiment_id" -o exp02_analytic.html
```

Repeat with `configs/experiments/exp02_branin.yaml` for the Branin arm.

### Recorded pipeline pilot

The pilot ran on an Apple M5 Mac (10 cores, 16 GB RAM), macOS 26.5.2, PostgreSQL 17
in Docker, Python 3.12, repository at merge commit including T-337 CLI fixes, one
worker. Wall time from CLI start to two completed campaigns was about 12 seconds.

```sh
roboprobe db upgrade
roboprobe --json experiment run docs/evidence/exp02-pilot/design.yaml \
  --workers 1 --raw-parquet docs/evidence/exp02-pilot/runs.parquet > run.json
experiment_id=$(python3 -c 'import json; print(json.load(open("run.json"))["experiment_id"])')
roboprobe --json experiment report "$experiment_id" -o report.html
```

## Results and interpretation

### Pipeline pilot (`multi_mode_6d`, reduced design)

| Strategy | Runs | Verdicts | Observed failures |
|----------|------|--------|-------------------|
| S-RANDOM | 8 | 8 pass | 0 |
| S-PROBE | 8 | 8 pass | 0 |

All sixteen episodes completed. Parquet export and HTML generation succeeded. With
one seed and no observed failures, the pilot supports **pipeline readiness only**;
median/IQR comparisons, Holm-adjusted p-values, and Â12 for H1–H2 remain open until
the preregistered 50-seed campaigns finish.

The Branin arm has not been executed on the full preregistered scale in this record.

## Deviations and threats

| Item | Preregistered | Recorded pilot |
|------|---------------|----------------|
| Seeds | 50 | 1 |
| Strategies | 8 | 2 (S-RANDOM, S-PROBE) |
| Budget per campaign | 150 | 8 |
| Arms completed | `multi_mode_6d` + `branin_falsify` | `multi_mode_6d` smoke only |

See [deviations.md](deviations.md).

## Raw data and reports

| Artefact | Path | SHA-256 |
|----------|------|---------|
| Pilot Parquet | [exp02-pilot/runs.parquet](exp02-pilot/runs.parquet) | `97b3e6cb56cab36696d397f9b2e18ed5952538f823ec96bbd55986b570b5718a` |
| Pilot HTML (regenerated locally) | `report.html` from `experiment report` | `86056df33bd51a8d49022c868bdca3581a4a85bfb81711057cc6bb4eb452eee4` on the pilot host |

Files above 5 MB belong in a GitHub Release asset, not git.
