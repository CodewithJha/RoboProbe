# Calibration / pre-registration deviations

Log every post-freeze change to S-PROBE defaults or benchmark thresholds here
(docs/19 §8). Empty means no deviations since T-061.

## T-105a EXP-02 / EXP-07 evaluation scale (2026-11-23)

| Experiment | Deviation | Rationale |
|------------|-----------|-----------|
| EXP-02 | Pipeline pilot: 1 seed, 2 strategies, budget 8 on `multi_mode_6d` only; Branin arm not run at preregistered scale | Validate experiment CLI persistence and reporting before 50×8×150 analytic campaigns ([#369](https://github.com/CodewithJha/RoboProbe/pull/369)) |
| EXP-07 | Preregistered three-arm comparison not executed; committed d=6 smoke design only | Kinematic full runs scheduled on compute lane (T-105b); see [EXP-07.md](EXP-07.md) |

## T-120a EXP-04 Gazebo / SC-4 (2026-11-23)

| Experiment | Deviation | Rationale |
|------------|-----------|-----------|
| EXP-04 | Preregistered 5×80 Gazebo matrix not executed; committed smoke design and SC-4 **PENDING** evidence only | Long compute runs on owner hardware; EXP-01 ([#208](https://github.com/CodewithJha/RoboProbe/issues/208)) not required to schedule Gazebo campaigns |
