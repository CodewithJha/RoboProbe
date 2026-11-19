# ADR-0003: Lightweight `kinematic2d` backend for development, CI and ground truth

| Field | Value |
|-------|-------|
| Status | Accepted |
| Date | 2026-11-19 |
| Deciders | Priyanshu Jha (owner) |
| Supersedes / Superseded by | – |

## Context

Gazebo episodes are slow and need a large Docker image; CI runners and early development need the full loop in seconds. Evaluating 'did the strategy find all failure modes?' needs a ground truth that is impossible to obtain from Gazebo (too expensive to sample densely).

## Decision

Implement a pure-Python/NumPy 2-D backend (`kinematic2d`) with the same `SimulatorBackend` interface, same parameters, same trace schema and the same perturbation formulas (shared modules), deterministic and ≥ 50× real time. Calibrate it to contain the designed failure mechanisms GT-A…GT-D (10 §7). Use it for all unit/integration tests, for large statistical experiments (30 seeds × strategies), and as ground truth via a dense 20 000-run reference set.

## Alternatives considered

| Option | Assessment |
|--------|-----------|
| Only Gazebo | CI impossible; experiments too slow for 30 seeds |
| Analytic functions only | No trajectories/oracles exercised; not a robot |
| MuJoCo as second backend | More physics than needed; still no navigation stack; larger effort |

## Consequences

- + Full loop testable in CI in minutes
- + Statistically powerful experiments
- + Ground-truth recall measurable
- − Results on k2d are not claims about real robots — reports must label backend clearly
- − Two backends to maintain (mitigated by shared modules & contract tests)

## Verification / compliance

Backend contract test suite runs against both backends; NFR-PERF-001 benchmark in CI.
