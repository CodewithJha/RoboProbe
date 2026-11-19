# ADR-0005: Intelligent selection: GP Bayesian optimisation + level-set active learning (BoTorch); RL deferred

| Field | Value |
|-------|-------|
| Status | Accepted |
| Date | 2026-11-19 |
| Deciders | Priyanshu Jha (owner) |
| Supersedes / Superseded by | – |

## Context

The concept allows RL, Bayesian optimisation, active learning or other adaptive methods. Our scenarios are static, episode-level vectors in d = 6–8 with budgets of 100–500 expensive, noisy evaluations. We need failures fast, *diverse* failures, and a calibrated uncertainty map.

## Decision

Use a **Gaussian-process surrogate on continuous robustness ρ** (BoTorch `SingleTaskGP`, Matérn-5/2 ARD) with **qLogNEI** for initial falsification, **expected violation + diversity penalty** for mode search, **straddle** for boundary refinement, and local refinement around new modes — combined in the phased `S-PROBE` strategy (07 §6). Use BoTorch directly (not Ax) for custom acquisitions. Implement RL-based AST only as future work for time-varying disturbances.

## Alternatives considered

| Option | Assessment |
|--------|-----------|
| Ax | Easier, but custom acquisitions/diversity are awkward; can wrap later |
| Optuna TPE | Good optimiser, no calibrated p_fail map; kept as optional comparison |
| scikit-optimize | Unmaintained |
| CMA-ES / CEM | Need more samples; CEM kept as optional baseline S-CEM |
| RL / AST | Designed for sequential disturbances; needs thousands of episodes; static params are not an MDP |
| Neural surrogate | Data-hungry at n ≤ 500 |

## Consequences

- + State-of-the-art sample efficiency in low d
- + Same model gives the risk map (p_fail) — one model, two uses
- + Explainable proposals (μ, σ, phase)
- − O(n³) GP cost; capped at 1 500 points
- − Hyper-parameters need validation (EXP-03 ablation)

## Verification / compliance

Benchmark tests in 07 §9 and EXP-01..EXP-03 in 19.
