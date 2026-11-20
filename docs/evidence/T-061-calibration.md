# T-061 — Benchmark threshold calibration (pre-registration)

**Date:** 2026-11-20  
**Scope:** Analytic benchmarks only (`branin_falsify`, `multi_mode_6d`). The EXP-01
evaluation space was **not** used (docs/19 §8 threat to internal validity).

## Frozen S-PROBE defaults

Taken from `selection.probe` / `ProbeDefaults` (docs/07 §6.3, docs/27):

| Key | Frozen value |
|-----|--------------|
| `n0_fraction` | 0.1 |
| `n0_min_factor` | 2 |
| `weights` | mode_search 0.6 / boundary 0.25 / refine 0.15 |
| `epsilon` | 0.05 |
| `lambda_div` | 1.0 |
| `kappa_radius` | 0.5 |
| `beta_straddle` | 1.96 |
| `refine_bisect_steps` | 4 |
| `refine_perturb_n` | 4 |
| `refine_perturb_std` | 0.05 |
| `adapt_window` | 20 |
| `adapt_shift` | 0.2 |
| `mode_search_floor` | 0.2 |

Any later change is a logged deviation in `docs/evidence/deviations.md`.

## Gate thresholds (with margin)

Committed in `backend/tests/benchmark/thresholds.yaml`:

| Gate | Threshold | Margin rationale |
|------|-----------|------------------|
| S-BO branin median first-fail | ≤ 25 | docs/18 §4.4 target; budget 60 |
| S-PROBE modes ≥ 3/4 in ≥ 80 % of seeds | budget 150 | docs/07 §9 / docs/18 §4.4 |
| S-PROBE median first-fail ≤ 0.5 × S-RANDOM | ratio 0.5 | docs/18 §4.4 |
| S-LSE boundary-band fraction vs S-RANDOM | +0.05 | isolates boundary refinement |
| Perf regression vs baselines | × 1.2 | docs/18 §6 (20 % slower fails) |

## How to reproduce

```bash
uv run --directory backend python ../scripts/calibrate_benchmarks.py --seeds 20 --budget 150
```

Raw JSON lands at `docs/evidence/T-061-raw.json` (optional artefact; not required in CI).

## Seeds

Fixed list `0..19` (inclusive), matching the benchmark modules.
