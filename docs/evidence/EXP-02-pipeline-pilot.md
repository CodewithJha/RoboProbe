# EXP-02 pipeline pilot

> Canonical evidence: [EXP-02.md](EXP-02.md).

## Design and hypotheses

This pilot checked that an analytical experiment could start, persist its
campaigns, export raw data, and render its report. It retained the EXP-02
seed root and used the six-dimensional multi-mode space. The statistical
hypotheses remain governed by the [preregistered EXP-02 design](../../configs/experiments/exp02_analytic.yaml).

The [pilot design](exp02-pilot/design.yaml) has SHA-256
`435a2ae303462a683e0e267d26832e34da1294cbaabf8f3f77fcf6ed25b9dada`.

## Environment and reproduction

The pilot ran on an Apple M5 Mac with ten cores and 16 GB of memory,
macOS 26.5.2, PostgreSQL 17 in Docker, Python 3.12, and one worker.
The experiment ID was `542da849-08a5-4a17-9379-e1944775078e`.
From CLI start to both complete campaign records, the pilot took about 12 seconds.

With a fresh RoboProbe database and its artifact store configured, run these
commands from the repository root.

```sh
roboprobe db upgrade
roboprobe --json experiment run docs/evidence/exp02-pilot/design.yaml \
  --workers 1 --raw-parquet runs.parquet > run.json
experiment_id=$(python3 -c 'import json; print(json.load(open("run.json"))["experiment_id"])')
roboprobe --json experiment report "$experiment_id" -o report.html
```

## Results and interpretation

| Strategy | Runs | Passes | Observed failures |
|----------|------|--------|-------------------|
| S-RANDOM | 8 | 8 | 0 |
| S-PROBE | 8 | 8 | 0 |

Both campaigns, Parquet export, and HTML generation completed. With a single
seed and zero observed failures, the result verifies the pipeline and leaves
the comparative hypotheses open.

## Deviations and threats

The pilot uses one seed, two strategies, and eight runs per campaign. The
preregistered EXP-02 design uses 50 seeds and 150 runs per campaign. The
paired Branin arm and the three EXP-07 arms were outside the pilot scope.

## Raw data and reports

The [raw Parquet data](exp02-pilot/runs.parquet) has SHA-256
`97b3e6cb56cab36696d397f9b2e18ed5952538f823ec96bbd55986b570b5718a`.
The generated pilot HTML had SHA-256
`86056df33bd51a8d49022c868bdca3581a4a85bfb81711057cc6bb4eb452eee4`.
The report command regenerates it for the local experiment ID.
