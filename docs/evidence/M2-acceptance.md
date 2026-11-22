# M2 scenario and kinematic2d acceptance

P0 verification on 2026-11-23 IST used the warehouse scenario and kinematic2d sources
at main commit `2171aa61`. GitHub recorded all 27 child issues, #32 through #58, as
closed and completed.

## Kinematic episode time and determinism

The nominal warehouse episode returned `SUCCEEDED` on all five runs with seed 7
on the Apple Silicon development host. Wall times were 0.647, 0.697, 0.512, 0.312,
and 0.565 seconds. The median was 0.565 seconds and the maximum was 0.697 seconds
against the two-second exit criterion.

The five runs produced the same trace-array SHA-256 used by the T-033d regression:
`fb019f3c0e367dcb4bbcec1ec2504865bfe62400364cb557a0d0986221a435f5`.
The success, deterministic trace, and timing checks all passed.

```sh
cd backend
uv run pytest -o addopts= -q tests/unit/backends/kinematic2d/test_episode.py
```

## Gazebo feasibility evidence

The [T-090 spike](T-090-gazebo-spike.md) records six successful warehouse Nav2 goals
on the CPU-rendered ARM64 Jazzy/Harmonic stack and measures concurrent real-time factor.
