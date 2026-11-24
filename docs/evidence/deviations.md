# Calibration / pre-registration deviations

Log every post-freeze change to S-PROBE defaults or benchmark thresholds here
(docs/19 §8). Empty means no deviations since T-061.

## T-105c SC-5 k2d replay cohort (2026-11-23)

| Item | Deviation | Rationale |
|------|-----------|-----------|
| EXP-01 `S-PROBE` replays | MET-06 measured on 6/30 preregistered seeds (pilot + five completed campaigns), not the full matrix | EXP-01 main runs still executing ([#208](https://github.com/CodewithJha/RoboProbe/issues/208)); measured cohort MET-06 = 1.0 with zero disagreements — see [SC-5-k2d.md](SC-5-k2d.md) |

## T-105a EXP-02 / EXP-07 evaluation scale (2026-11-23)

| Experiment | Deviation | Rationale |
|------------|-----------|-----------|
| EXP-02 | Pipeline pilot: 1 seed, 2 strategies, budget 8 on `multi_mode_6d` only; Branin arm not run at preregistered scale | Validate experiment CLI persistence and reporting before 50×8×150 analytic campaigns ([#369](https://github.com/CodewithJha/RoboProbe/pull/369)) |
| EXP-07 | Preregistered three-arm comparison not executed; committed d=6 smoke design only | Kinematic full runs scheduled on compute lane (T-105b); see [EXP-07.md](EXP-07.md) |

## T-120a / T-120b / T-120c Gazebo studies (2026-11-23)

| Experiment | Execution detail | Rationale |
| ---------- | ---------------- | --------- |
| [EXP-04](EXP-04.md) | The OFAT arm used a separate 30-episode campaign and the first registered common seed. | The schema v1 design has one budget field. |
| [EXP-04](EXP-04.md) | A setup-only run stopped on package metadata retrieval. The corrected run retained the original simulator and scientific inputs. | The runner can identify its installed vendor package directly. |
| [EXP-04](EXP-04.md) | No pooled mode met the multifactor confirmation prerequisites. A separate GUI replay recorded a collision medoid. | The sample yielded a negative SC-4 result. |
| [EXP-05](EXP-05.md) | The frozen schema-v1 file recorded one profile field. The collector explicitly applied the EXP-04-informed tuned profile to arm B. | The two arms kept the registered seeds, scenario, strategy settings and budgets. |
| [EXP-06](EXP-06.md) | After the first drain expired, the analysis retained eight completed medoid replays and filled the two pending fresh-seed slots from the recovery. | The recovery extended only the worker drain time. |
