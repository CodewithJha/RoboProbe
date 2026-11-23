# EXP-01 warehouse reference

## Design and provenance

The raw reference contains 20,000 scrambled Sobol scenarios from the
[preregistered evaluation plan](../19-evaluation-and-experiment-plan.md#3-metric-definitions).
The seed is `20261119`, the space is `warehouse_v1@d098010f625c`, and the
simulator model is `kinematic2d_v1`.

Recovery rejudged 16,241 preserved trace files and ran the remaining 3,759
scenarios on macOS 26.5.2 (arm64). Before recovery, five sampled preserved
episodes reproduced their trace bytes and verdicts. The recovery validated
the seed, model, task goal, obstacle placement, and world file for each
episode. Each row has the original sample ordinal, coordinates, robustness,
verdict, and primary failure class. Independent verification regenerated the
full Sobol sequence and matched all coordinates and ordinals in order.

## Observed outcomes

| Outcome | Reference rows |
|---|---:|
| PASS | 9,087 |
| FAIL | 10,913 |
| INVALID | 0 |

| Primary failure class | Reference rows |
|---|---:|
| F-STUCK | 7,457 |
| F-TIMEOUT | 2,386 |
| F-LOC | 1,050 |
| F-PLAN | 20 |

The ground-truth label column is empty. SC-2 and SC-3 depend on the reviewed
reference mode assignments and the complete EXP-01 campaigns in
[#208](https://github.com/CodewithJha/RoboProbe/issues/208).

## Reproduction and artifacts

```sh
roboprobe --json reference generate --space warehouse_v1 --seed 20261119 \
  --n 20000 --output warehouse_v1.parquet
shasum -a 256 warehouse_v1.parquet
```

The [raw Parquet](exp01-reference/warehouse_v1.parquet) has SHA-256
`7f4bf51b1809e7f850a9ad9b6020958a22c056f1f48c2864104b5017d0f77729`.
Its [manifest](exp01-reference/warehouse_v1.manifest.json) records the sample
and simulator identity. The [verification record](exp01-reference/verification.json)
records the recovered counts and outcome tallies.
