# ADR-0014: Hierarchical seeding and per-run provenance manifests

| Field | Value |
|-------|-------|
| Status | Accepted |
| Date | 2026-11-19 |
| Deciders | Priyanshu Jha (owner) |
| Supersedes / Superseded by | – |

## Context

Rare failures are only valuable if reproducible. Randomness enters through strategies, sensor noise, perception models and simulators.

## Decision

A single campaign seed feeds `numpy.random.SeedSequence`; child seeds are derived by stable keys (`strategy`, `run/<ordinal>/<repeat>`, `sensor`, `perception`, `localisation`). Each run stores a manifest with code version, dependency lock hash, image digest, seeds, scenario values, materialised file hashes and config snapshot (21 §4).

## Alternatives considered

| Option | Assessment |
|--------|-----------|
| Global random seed | Order-dependent; parallel runs break reproducibility |
| No manifest | Cannot explain differences between replays |

## Consequences

- + Bit-exact k2d replays, best-effort Gazebo replays
- + Auditable results

## Verification / compliance

NFR-REP-001 test; replay agreement MET-06.
