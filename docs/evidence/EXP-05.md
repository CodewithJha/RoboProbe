# EXP-05 — Gazebo profile A versus profile B

## Design and inputs

The preregistered design ran all six 80-episode S-PROBE campaigns on the
warehouse space. Each group of two campaigns shares its original campaign
seed, and each arm was simulated afresh. All 480 episodes reached `DONE`
with a usable verdict. [Native profile comparison](https://github.com/CodewithJha/RoboProbe/actions/runs/45120816975)

[Profile A](../../configs/sut_profiles/tb4_nav2_default.yaml) retained the
original Nav2 settings. [Tested Profile B](https://github.com/CodewithJha/RoboProbe/blob/e6387727727fc4aeadfbec367671004b853826ee/configs/sut_profiles/tb4_nav2_tuned.yaml)
changed local and global costmap inflation scaling from 3.0 to 2.0, extending
obstacle cost pressure within the existing 0.70 m radius. In the paired
[EXP-04](EXP-04.md) matrix, all 449 collision verdicts occurred below 0.70 m
episode minimum obstacle clearance. The other 258 episodes at or above
0.70 m had zero collisions. This observation motivated the single tuning
change. Both arms retained the same speed mapping and classification rules.

The exact [preregistered YAML](https://github.com/CodewithJha/RoboProbe/blob/e6387727727fc4aeadfbec367671004b853826ee/configs/experiments/exp05_profiles.yaml)
has SHA-256 `ce40a7f73893dc10f1ae04c5af53f04bb4f31cc723d3f142c6692705db10b24a`.
Its schema-v1 file used the same default profile field for both arms. The
[original collector](https://github.com/CodewithJha/RoboProbe/blob/e6387727727fc4aeadfbec367671004b853826ee/scripts/collect_exp05.py)
applied the tuned profile to the B arm only after it matched the frozen plan.
The [current CLI design](../../configs/experiments/exp05_profiles.yaml)
declares that assignment explicitly using
[`tb4_nav2_costmap_decay`](../../configs/sut_profiles/tb4_nav2_costmap_decay.yaml),
a distinct profile ID with the same tested simulator parameters. Published
[`tb4_nav2_tuned`](../../configs/sut_profiles/tb4_nav2_tuned.yaml) retains its
existing immutable registration. The CLI design retains the original scenario
space, matched seed schedule, strategy settings, budget and batch size.

The tested profile A and B file SHA-256 values are
`125ce5539a41d8b39ef1d850dbead8aee02e2fac16f1c9708441eb7ece6a4944` and
`65072c480d58e780282a8536e903bb32a2a88db31146631cb9592474f937edfb`,
respectively. The verifier restored all campaign databases and checked the
immutable raw Parquet hashes and completed analysis reports.
[Database and report verification](https://github.com/CodewithJha/RoboProbe/actions/runs/45334012957)

## Estimated volumes and scores

The risk map evaluates 8,192 scrambled Sobol points for each fitted campaign
model. Percentages in parentheses are Wilson 95% intervals for each region
volume under its fitted model. A and B use the same Sobol points within each
seed pair.

| Replicate | Profile | SAFE | UNCERTAIN | FAILURE | Robustness score |
| --------- | ------- | ---- | --------- | ------- | ---------------- |
| 0 | A | 7.98% (7.42–8.59%) | 48.56% (47.48–49.64%) | 43.46% (42.39–44.53%) | 0.32263 |
| 0 | B | 23.52% (22.62–24.45%) | 28.21% (27.25–29.20%) | 48.27% (47.19–49.35%) | 0.37628 |
| 1 | A | 12.17% (11.48–12.90%) | 46.46% (45.38–47.54%) | 41.37% (40.31–42.44%) | 0.35400 |
| 1 | B | 17.79% (16.97–18.63%) | 32.63% (31.62–33.65%) | 49.58% (48.50–50.67%) | 0.34100 |
| 2 | A | 12.07% (11.38–12.80%) | 44.25% (43.18–45.33%) | 43.68% (42.61–44.75%) | 0.34198 |
| 2 | B | 17.66% (16.85–18.50%) | 36.61% (35.57–37.66%) | 45.73% (44.65–46.81%) | 0.35968 |

## Paired MET-07 and failure modes

The paired score differences for the three registered seeds were +0.05365,
−0.01300, and +0.01770 (mean +0.01945). Profile B produced a larger estimated
SAFE volume and a larger FAILURE volume in all three pairs, with less
UNCERTAIN volume. The estimated robustness score fell in one pair.
The conditional paired 95% intervals by seed were +0.04779 to +0.05951,
−0.01971 to −0.00616, and +0.01190 to +0.02362. The stratified common-point
bootstrap 95% interval for the mean was +0.01599 to +0.02295. The reconstruction
used the original Ubuntu runtime, matched all six stored risk summaries
exactly, and checked equality of the two Sobol point arrays within each seed.
[Paired intervals and point labels](https://github.com/CodewithJha/RoboProbe/actions/runs/45335161116/artifacts/14892913859)

This is a positive mean contrast conditional on the fitted risk models. The
three independent seed pairs give a descriptive seed-resampled interval of
−0.00635 to +0.04586. **The study did not establish H6 across campaign seeds.**

The original episode verdicts were 213 failures under A and 214 under B,
with respectively 153 and 155 collisions and 60 and 59 timeouts. The verdict
counts describe the adaptive sample. The volume estimates describe the
modelled scenario space.
Joint HDBSCAN over the failures from A and B identified two modes in each
replicate, corresponding to collision and timeout. Both profiles had members
in both modes for every replicate. This check used persisted trajectory
features with missing-value handling, so it could miss a finer-grained mode.

The optional feature-importance and rule extractors rejected the three
64-bit campaign seeds in the scikit-learn estimators that require 32-bit
`random_state` values. The six core risk analyses completed and retain their
volume outputs. The optional feature-importance and rule evidence is
unavailable for this comparison.
