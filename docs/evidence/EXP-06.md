# EXP-06 — Gazebo replay reproducibility

## Result

The ten [EXP-04](EXP-04.md) pooled medoids each contributed five same-seed and
five fresh-seed replays. An agreement requires the same verdict and primary
failure class. Each medoid contributes equally to MET-06.

| Cohort | Agreements | Rate | Wilson 95% CI |
| ------ | ---------- | ---- | ------------- |
| Same seed (MET-06) | 48/50 | 0.96 | 0.865–0.989 |
| Fresh seeds | 40/50 | 0.80 | 0.670–0.888 |

**SC-5 Gazebo passed.** Same-seed agreement exceeded the 0.80 point target.
These Wilson intervals describe the 50 trials per cohort. Five trials share
each medoid, so the intervals do not establish precision across unseen modes.
All 50 collision replays across both cohorts preserved the source class.
None of the 100 trace hashes matched the originals byte for byte.

| Mode | Original run ID | Class | Same seed | Fresh seed |
| ---- | --------------- | ----- | --------- | ---------- |
| EXP04-R0-FM01 | `01a206b8-bcb9-7023-9fe3-54fba31e4736` | F-TIMEOUT | 4/5 | 2/5 |
| EXP04-R0-FM02 | `01a2069d-17ab-77bb-aa96-d6b49e87cea4` | F-COL | 5/5 | 5/5 |
| EXP04-R1-FM01 | `01a206ab-c990-73a9-9c0c-347b4b0f9051` | F-TIMEOUT | 4/5 | 3/5 |
| EXP04-R1-FM02 | `01a20690-56ba-75af-91ae-4428f3ec53ff` | F-COL | 5/5 | 5/5 |
| EXP04-R2-FM01 | `01a206a7-d28f-77b1-bef0-866908ceba47` | F-TIMEOUT | 5/5 | 3/5 |
| EXP04-R2-FM02 | `01a206cc-2ca2-728d-94bf-a61deaa2eeff` | F-COL | 5/5 | 5/5 |
| EXP04-R3-FM01 | `01a206ba-a9d0-7420-8b7b-c4b00be4b560` | F-COL | 5/5 | 5/5 |
| EXP04-R3-FM02 | `01a206a0-e62f-7649-a412-6dc6837604ae` | F-TIMEOUT | 5/5 | 5/5 |
| EXP04-R4-FM01 | `01a206ac-14ad-756f-82ba-d6c14b0d42af` | F-COL | 5/5 | 5/5 |
| EXP04-R4-FM02 | `01a20691-62bb-76e4-9ffd-ba4dd3bccddd` | F-TIMEOUT | 5/5 | 2/5 |

## Disagreements and environment

All 12 disagreements were originally `F-TIMEOUT` and passed in replay. The
two same-seed discrepancies reached the goal at 44.052 and 61.851 simulated
seconds. The original traces ended at 43.650 and 61.152 seconds with the goal
still outstanding. Recorder timestamps remained increasing. Across the
originals and disagreements, median sample spacing was 51 ms and the largest
observed gap was 63 ms. The episode logs had no explicit DDS drop or warning
indicators. The matching manifests retained the same SUT configuration, task,
oracle settings, simulator package pins, and scenario. The run-specific host
and image provenance differs between machines. The recorded timing resolves
the different outcome at the goal boundary. It does not isolate a simulator
or middleware cause.

Each medoid ran on its own Ubuntu 24.04 Gazebo worker. The hosted source
restored the original campaign and trace data from their verified archive,
then submitted five replays per seed cohort. For EXP04-R3-FM02, the initial
600-second worker drain completed all five same-seed and three fresh-seed
trials. A second run used a 1,800-second drain with the same episode timeout
and the same five fresh seeds. The analysis retains all original completed
trials and uses only the two missing fresh seed slots from the recovery.

The native runs retain the original database snapshots, replay and source
manifests, traces, logs, and CLI result files. The independent verifier
restored the snapshots and compared replay IDs, scenario values, seeds, and
content-addressed hashes before computing agreement.
[Initial replays](https://github.com/CodewithJha/RoboProbe/actions/runs/45119937477) ·
[Single-mode recovery](https://github.com/CodewithJha/RoboProbe/actions/runs/45127477971) ·
[Verified summaries](https://github.com/CodewithJha/RoboProbe/actions/runs/45334012957)
