# EXP-04 — Gazebo RANDOM vs PROBE

## Design and provenance

The native Ubuntu 24.04 collection completed the registered 800-episode
RANDOM/PROBE matrix and the separate 30-episode OFAT campaign. All 830 original
episodes reached `DONE`. Independent verification compared the proposal-order
Parquet rows with the restored PostgreSQL data and verified the SHA-256 of the
registered trace, manifest, and log artifacts. [Native collection workflow](https://github.com/CodewithJha/RoboProbe/actions/runs/45108261669)

The frozen design SHA-256 is
`1e5b74000d42ae4b2be121d5d94aec31e55c97c915e1733e110f07129fb34d7a`.
All cells used `tb4_nav2_default`, seed root 20261119, batch size 1, and one
Gazebo worker per host. The OFAT campaign used the first registered common seed
and stays outside the paired statistical comparison. The study ran after the
current-main physical preflight passed. [Preflight](https://github.com/CodewithJha/RoboProbe/actions/runs/45105276569)

## Outcome and discovery

| Replicate | Shared seed | RANDOM failures | PROBE failures | Pooled mode hits (R / P) | First failure (R / P) |
|-----------|-------------|-----------------|----------------|--------------------------|-----------------------|
| 0 | `2179776959060123449` | 65/80 | 72/80 | 2 / 2 | 1 / 1 |
| 1 | `3234007610454330333` | 70/80 | 71/80 | 2 / 2 | 1 / 1 |
| 2 | `5655397147810014433` | 63/80 | 69/80 | 2 / 2 | 1 / 1 |
| 3 | `5748673534120150065` | 67/80 | 66/80 | 2 / 2 | 1 / 1 |
| 4 | `227276608207929910` | 69/80 | 69/80 | 2 / 2 | 1 / 1 |

PROBE had 347 failures in 400 episodes, RANDOM 334 in 400, and the supplementary
OFAT campaign 20 in 30. The matched campaigns recorded 449 F-COL and 232
F-TIMEOUT outcomes. No episode returned INVALID. The supplementary OFAT
campaign is excluded from these matched failure-class counts.

| Metric | RANDOM median (95% bootstrap CI) | PROBE median (95% bootstrap CI) | Holm-adjusted p | Â12 |
|--------|----------------------------------|---------------------------------|-----------------|-----|
| MET-01 failure discovery rate | 0.8375 (0.7875–0.8750) | 0.8625 (0.8250–0.9000) | 0.2045 | 0.76 |
| MET-02 known pooled modes hit | 2 (2–2) | 2 (2–2) | 1.0000 | 0.50 |
| MET-03 simulations to first failure | 1 (1–1) | 1 (1–1) | 1.0000 | 0.50 |

Both strategies found a failure on the first episode of every paired cell and
hit both identified pooled modes in every replicate. With five replicates per
arm, these data give no statistical support for a discovery advantage.

## SC-4 interaction assessment

The registered pooled analysis used RoboProbe's weighted HDBSCAN pipeline
independently for each paired seed. All ten primary modes were chiefly collision
or timeout. No mode had two or more characteristic parameters under the
configured coverage rule. The original worker summaries omitted trajectory
keys used by the feature builder. That builder applied its documented missing
metric handling.

A sensitivity analysis rebuilt trajectory features from the 701 original
failing traces and their stored oracle violation times. It recovered progress
at the oracle violation for 471 failures. In the remaining 230, the timeout
oracle timestamp was outside the recorded trace, so progress was left missing.
All ten mode memberships were unchanged and three representative medoids
changed. The trajectory-aware analysis again found zero modes with two or more
characteristic parameters. Under the registered mode-selection rule there was
no multifactor candidate to take into the three-repeat confirmation procedure.
**The study did not meet SC-4.** The result applies to this configuration and
budget.

## Supplemental Gazebo replay and capture

As a reproducible example from the observed collision mode, the study replayed
EXP04-R0-FM02 medoid `01a2069d-17ab-77bb-aa96-d6b49e87cea4` with its original
scenario and seed. GUI replay `01a20734-2b8f-7217-9651-b77806d4935c` reproduced
the `FAIL/F-COL` verdict and class. The genuine 1280×720 Gazebo Sim capture
runs for 103.933 seconds. The replay attached its MCAP bag.
[GUI replay workflow](https://github.com/CodewithJha/RoboProbe/actions/runs/45127309138)

Download `exp04-gui-replay-EXP04-R0-FM02-attempt1` from the workflow's Artifacts section.

| File | SHA-256 |
|------|---------|
| `gazebo-replay.mp4` | `22cea34998c0b5a00feaff5f957341f2ce6eadee3598dc3eaa33e6c9ee88b31b` |
| `gazebo-replay.mcap` | `14980f738a0192435b7c6db90d500e384366785a899d5b86e99f7fd2f3cd50e2` |

The collision replay is a demonstration of an observed single failure class.
The interaction assessment above uses the five paired campaign pools.

GitHub Actions applies a retention period to the source archive. The asset
hashes identify the retained files.

## Reproduction

The [exact collection source](https://github.com/CodewithJha/RoboProbe/tree/79b3c3e91a9ac1eb251e74a147754d9f2f410471)
runs the frozen [EXP-04 design](../../configs/experiments/exp04_gazebo.yaml)
with native Gazebo Harmonic, ROS 2 Jazzy, Nav2, pinned Fuel assets, software
rendering, and isolated PostgreSQL per matrix cell. Each cell starts one
Gazebo worker. The successful workflow records the runner environment,
campaign manifests, raw Parquet, database dumps, and per-episode artifacts.

The setup-only first attempt required a package-metadata correction before
the successful collection. The successful workflow retained the preregistered
scenario space, profile, seeds, batch size and budgets. The OFAT arm is
documented separately because the experiment schema has a single budget.
[Setup-only attempt](https://github.com/CodewithJha/RoboProbe/actions/runs/45105992162)

The ten paired medoids and their repeat results are recorded in
[EXP-06](EXP-06.md).
