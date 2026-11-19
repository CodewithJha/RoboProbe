# ADR-0006: Continuous robustness-valued (STL-style) oracles

| Field | Value |
|-------|-------|
| Status | Accepted |
| Date | 2026-11-19 |
| Deciders | Priyanshu Jha (owner) |
| Supersedes / Superseded by | – |

## Context

Boolean pass/fail gives the selector almost no gradient: thousands of PASS runs look identical. Falsification literature (S-TaLiRo, Breach, VerifAI) uses quantitative robustness of temporal-logic specifications.

## Decision

Every oracle returns a robustness `r ∈ [−1,1]` (negative ⇔ violated) defined in 08 §3; the run robustness is `ρ = min_k r_k`. Verdict and ρ must agree (`FAIL ⇔ ρ < 0`). Within collisions, impact speed keeps ρ informative.

## Alternatives considered

| Option | Assessment |
|--------|-----------|
| Boolean only | No learning signal before first failure |
| Full STL library (e.g. rtamt) | Powerful but adds dependency/complexity; may be added as an oracle plugin later |

## Consequences

- + Selector learns 'near misses'
- + GP regression instead of classification
- − Normalisation constants are design choices (config, documented)

## Verification / compliance

Oracle golden-trace tests; invariant test FAIL ⇔ ρ<0.
