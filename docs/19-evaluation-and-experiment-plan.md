# 19 — Evaluation & Experiment Plan

> Related: [01 §9 Research question](01-vision-and-product-brief.md#9-research-question) · [07](07-intelligent-test-selection-algorithms.md) · [09 §5.5](09-failure-analysis-and-risk-mapping.md) · [26 PRD KPIs](26-product-requirements-document.md)

## 1. Research question & hypotheses

RQ: *Can an intelligent testing system learn from simulation outcomes and efficiently discover rare combinations of conditions that expose hidden weaknesses in a robotic system?*

| H | Statement | Metric(s) | Experiment |
|---|-----------|-----------|-----------|
| H1 | S-PROBE needs fewer simulations to the first failure than S-RANDOM and S-LHS | MET-03 | EXP-01, EXP-02, EXP-04 |
| H2 | S-PROBE discovers more distinct failure modes per budget | MET-02, MET-09 | EXP-01, EXP-02, EXP-04 |
| H3 | S-PROBE discovers interaction failures that S-OFAT cannot | MET-02 (interaction modes), interaction test 09 §6 | EXP-01, EXP-04 |
| H4 | S-PROBE's risk map is at least as accurate as one from random samples | MET-08 | EXP-01 |
| H5 | Each S-PROBE ingredient contributes | MET-02, MET-03 | EXP-03 |
| H6 | Discovered failures are reproducible and guide a robustness improvement | MET-06, MET-07 | EXP-05, EXP-06 |

## 2. Units of analysis

One **campaign** = (strategy, seed, budget, backend, space, SUT profile). Every metric is computed per
campaign; distributions across seeds are compared between strategies.

## 3. Metric definitions

Notation: campaign runs `1..B` in proposal order; valid runs `V` (verdict ≠ INVALID); failing runs `F ⊆ V`; `t_i` wall time of run i.

| ID | Name | Formula | Notes |
|----|------|---------|-------|
| MET-01 | Failure discovery rate | `FDR = \|F\| / \|V\|`; also `FDR_h = \|F\| / (Σ t_i / 3600)` (failures per CPU-hour) | higher is better, but rewards repeating one mode — read with MET-02 |
| MET-02 | Unique failure modes | k2d: `\|{g ∈ GT : ∃ x ∈ F, label_ref(x) = g}\|` where `label_ref` = GT mode of the nearest failing reference point within radius `r = 0.05` (unit L2), else "novel"; Gazebo: number of modes from a **pooled clustering** (all strategies' failures for the same seed index clustered jointly; count clusters each strategy hits) | pooled clustering avoids rewarding a strategy for its own fragmentation |
| MET-03 | Simulations to first failure | `N1 = min{i : i ∈ F}`; if `F = ∅`, right-censored at `B` | compare with Mann–Whitney (censored set to `B+1`) and log-rank |
| MET-04 | Coverage | (a) 2-way bin coverage `C2 = (# of (i,j,b_i,b_j) cells hit) / (C(d,2)·k²)` with `k = 5` bins/dim; (b) failure-region coverage `CF = \|{y ∈ REF_fail : ∃x∈F, ‖x−y‖ < r}\| / \|REF_fail\|` (k2d only) | (a) exploration breadth, (b) how much of the true failure set was "touched" |
| MET-05 | Cost per failure mode | `CPM = Σ t_i / MET-02` (s) and `SPM = B / MET-02` (sims) | ∞ if no mode |
| MET-06 | Reproducibility | for each mode medoid replayed `R = 5` times with original seed: `rep = (# replays with same verdict & class) / R`; campaign value = mean over modes | k2d expected 1.0 |
| MET-07 | Robustness improvement | `Δ = robustness_score(profile_B) − robustness_score(profile_A)` with bootstrap CI (09 §5.4) | EXP-05 |
| MET-08 | Boundary accuracy | balanced accuracy of `p_fail(x) > 0.5` vs reference verdicts on `REF` (k2d) | also failure recall and F1 |
| MET-09 | Discovery-curve AUC | `AUC = (1/B) Σ_{n=1..B} modes(n)/\|GT\|` | single number summarising the curve |

Reference set `REF` (k2d): 20 000 scrambled-Sobol scenarios, seed 20261119, each run once (deterministic backend), stored as artefact with hash; GT modes = HDBSCAN clusters of `REF_fail` reviewed manually and mapped to GT-A…GT-D (+ any emergent mode, recorded).

The EXP-02 `multi_mode_6d` arm labels observed failures with the benchmark's noise-free
canonical modes A–D ([07 §9](07-intelligent-test-selection-algorithms.md)).
An observed failure outside all four modes does not increase MET-02 or the MET-09 discovery
curve. The raw experiment Parquet includes the unit-cube vector and a comparison-run flag so a
reader can recompute these results. The Branin and warehouse variants require their own reviewed
mode assignments before the comparison can accept MET-02 or MET-09.

## 4. Experiment matrix

| ID | Backend | Space | Strategies | Seeds | Budget | Est. compute | Purpose |
|----|---------|-------|-----------|-------|--------|--------------|---------|
| EXP-01 | kinematic2d | warehouse_v1, d=6 (+ d=8 variant) | RANDOM, LHS, SOBOL, OFAT, GRID, BO, LSE, PROBE (+CEM optional) | 30 | 200 | 8×30×200 = 48 000 runs ≈ 2–3 h on 6 workers | main comparison H1–H4 |
| EXP-02 | analytic `multi_mode_6d`, `branin_falsify` | – | same | 50 | 150 | minutes | sanity + algorithm-only evidence |
| EXP-03 | kinematic2d | d=6 | PROBE, PROBE−diversity, PROBE−boundary, PROBE−refine, PROBE ε=0, BO, LSE | 30 | 200 | ≈ 2 h | ablation H5 |
| EXP-04 | gazebo_nav2 | d=6 | RANDOM, PROBE (OFAT once, 30 runs) | 5 | 80 | 10 campaigns × 80 × ~100 s ≈ 22 h (spread over nights) | real-stack evidence H1–H3 |
| EXP-05 | gazebo_nav2 (+ k2d) | d=6 | PROBE on profile A (default Nav2) and profile B (tuned after EXP-04) | 3 | 80 | ≈ 7 h | robustness improvement H6 |
| EXP-06 | gazebo_nav2 | – | replay of each EXP-04 mode medoid × 5 | – | – | ≈ 2 h | reproducibility H6 |
| EXP-07 | kinematic2d | d=6 vs d=8; noise ×2 | RANDOM, PROBE | 30 | 300 | ≈ 2 h | scalability with dimension/noise |

Budgets are upper bounds. The preregistered S-GRID design has 64 scenarios per seed for
EXP-01 and the 6-D EXP-02 arm, and 144 per seed for the 2-D EXP-02 arm.
Report the number of episodes actually collected for each arm.

Experiment YAMLs: `configs/experiments/exp01_k2d_main.yaml` …, executed with `roboprobe experiment run`;
validated by `schemas/experiment.schema.json`. Example (EXP-01, abridged):

```yaml
schema_version: 1
id: exp01_k2d_main
name: kinematic2d main comparison (H1-H4)
backend: kinematic2d
space: {id: warehouse_v1}
sut_profile_id: k2d_default
strategies:
  - {id: S-RANDOM}
  - {id: S-SOBOL}
  - {id: S-BO}
  - {id: S-PROBE, params: {epsilon: 0.05}}
seeds: {root: 20261119, count: 30}   # campaign seed k = derive_seed(root, "rep", k) (21 §3)
budget: 200
metrics: [MET-01, MET-02, MET-03]
```

## 5. Statistical analysis protocol

1. For each metric and each pair (S-PROBE vs X): two-sided **Mann–Whitney U** test, α = 0.05; **Holm–Bonferroni** correction over all pairs within a metric.
2. Effect size **Vargha–Delaney Â12** (probability that S-PROBE beats X): negligible < 0.56 ≤ small < 0.64 ≤ medium < 0.71 ≤ large.
3. Medians with **bootstrap 95 % CIs** (10 000 resamples, percentile method, seed fixed).
4. MET-03 additionally with Kaplan–Meier curves and the log-rank test (censoring at B).
5. Report all strategies, all metrics, including where S-PROBE is *not* better (no cherry-picking).
6. Common random numbers: seed index `k` uses the same simulator seed stream for all strategies (14 §8).
7. Pre-registration: this document fixes metrics/tests before EXP-01 is run; deviations are logged in `docs/evidence/deviations.md`.
Implementation: `roboprobe.metrics.statistics` (SciPy `mannwhitneyu`, own Â12, own bootstrap; `lifelines` not used to avoid dependency — log-rank implemented in ~40 lines and unit-tested against a published example).

## 6. Success thresholds (link to 01 §7)

SC-1: MET-03 median(S-PROBE) ≤ 0.5 × median(S-RANDOM), p_Holm < 0.05 (EXP-01). SC-2: MET-02 Â12 ≥ 0.64 vs RANDOM. SC-3: GT-A found in ≥ 90 % of PROBE seeds within 200 sims. SC-4: ≥ 1 interaction mode on Gazebo (EXP-04). SC-5: MET-06 = 1.0 (k2d), ≥ 0.8 (Gazebo).

## 7. Outputs

Experiment report (HTML): design table, per-metric box plots, discovery curves with CI bands, KM curves, statistics tables, case gallery, threats to validity, environment manifest (hardware, versions). Raw data export as Parquet for independent re-analysis.

## 8. Threats to validity

| Type | Threat | Mitigation |
|------|--------|-----------|
| Internal | Tuning S-PROBE on the same space it is evaluated on | Hyper-parameters fixed on analytic benchmarks (EXP-02) before EXP-01; d=8 and noise variants as held-out settings |
| Internal | Bugs in metric code | Unit tests with hand-computed examples; independent re-computation notebook |
| Construct | "Mode" definition depends on clustering | Pooled clustering; GT-based count on k2d; sensitivity analysis over `min_cluster_size` |
| Construct | Robustness normalisation favours some failure classes | Report per-class counts; ablation with boolean-only signal (classification GP) as optional check |
| External | kinematic2d ≠ real robot | Gazebo EXP-04/05; claims scoped per backend |
| External | One task, one world | Stated as limitation; architecture supports more tasks |
| Conclusion | Few Gazebo seeds | Report descriptive statistics + effect sizes; no strong claims from p-values with n=5 |
| Reliability | Gazebo non-determinism | Replays (EXP-06), learned noise in GP |
