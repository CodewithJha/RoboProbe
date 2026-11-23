# T-098 warehouse acceptance evidence

The [nightly acceptance](../18-testing-strategy-and-qa.md#48-gazebo-backend-sim-tests-nightly)
requires at least four passes from five nominal trials and an `F-COL` verdict for an on-path
pallet at 5 lux. The trials used the pinned Jazzy/Harmonic worker image from
[#362](https://github.com/CodewithJha/RoboProbe/pull/362), with its Cyclone DDS configuration,
a warmed read-only Fuel cache, software GL on ARM64, and the merged slot allocator from
[#368](https://github.com/CodewithJha/RoboProbe/pull/368). Each trial ran in a Linux-native
temporary directory. The warehouse and task came from main at `423d68c`.

## Shipped default profile

The default `tb4_nav2_default` profile inherited the stock 20 ms Nav2 behavior-tree action
acknowledgement setting. The production verdict engine accepted only one of the five nominal
trials. The dark canonical episode used seed 1, `obstacle.clearance=0.0`, and
`env.illuminance=5.0`. The other scenario values stayed nominal.

| Case | Seed | Nav2 terminal state | RoboProbe verdict | Simulated s | Closest ground truth to goal (m) |
|------|------|---------------------|------------------|-------------|----------------------------------|
| Nominal | 1 | ABORTED | FAIL / F-TIMEOUT | 49.209 | 0.294 |
| Nominal | 2 | ABORTED | FAIL / F-TIMEOUT | 6.801 | 11.298 |
| Nominal | 3 | ABORTED | INVALID / F-INFRA | 0.600 | 12.916 |
| Nominal | 4 | SUCCEEDED | FAIL / F-TIMEOUT | 49.212 | 0.301 |
| Nominal | 5 | SUCCEEDED | PASS | 49.488 | 0.224 |
| Canonical | 1 | ABORTED | FAIL / F-TIMEOUT | 16.059 | 8.898 |

The Nav2 logs show acknowledgement timeouts for `compute_path_to_pose` in nominal seed 1
and `follow_path` in nominal seeds 2 and 3 and the canonical run. Nominal seed 3 recorded
a 0.549 s trace and failed the existing short-trace validity check. Nominal seed 4’s closest
sampled ground truth, 0.301 m, was outside the task’s 0.250 m tolerance. Nav2 reported
success for that seed. The canonical default reached a minimum clearance of 1.773 m and recorded zero
contact samples before aborting.

## Opt-in action timeout profile

A controlled canonical repeat changed only the behavior-tree acknowledgement window from
20 ms to 1,000 ms. The opt-in profile
[`tb4_nav2_ack_1000ms`](../../configs/sut_profiles/tb4_nav2_ack_1000ms.yaml) carries that
setting. The run recorded actual contact at 22.953 simulated seconds and 0.260 m/s,
with 539 contact samples and minimum clearance 0.000 m. The production oracle classified the
case as `FAIL / F-COL`. Nav2 subsequently reported `SUCCEEDED` at 49.845 simulated seconds.
The run produced a 997-row Trace v1 and a 1,007,320-byte MCAP. The manager measured real-time
factor 0.926.

The opt-in test uses this named profile and the real backend and oracle pipeline. From
`backend/` inside the sourced worker image, with the repository and Fuel cache available:

```bash
python -m pytest -m sim --backend gazebo_nav2 tests/sim/test_canonical_collision.py
```

The episode directory contains the real trace, simulator log, terminal action report,
`acceptance.json`, and MCAP. The default-profile nominal gate and the three scheduled green
nights remain open under [#205](https://github.com/CodewithJha/RoboProbe/issues/205).
