# ADR-0012: Failure analysis: HDBSCAN + SHAP + decision-tree rules

| Field | Value |
|-------|-------|
| Status | Accepted |
| Date | 2026-11-19 |
| Deciders | Priyanshu Jha (owner) |
| Supersedes / Superseded by | – |

## Context

We must group failures into modes without knowing their number, explain parameter influence and interactions, and give human-readable conditions.

## Decision

HDBSCAN (scikit-learn) on weighted feature vectors; HistGradientBoosting + SHAP TreeExplainer (incl. interaction values) for importance; shallow decision tree for rules; GP lengthscales as cross-check; explicit confirmatory interaction test (09 §6).

## Alternatives considered

| Option | Assessment |
|--------|-----------|
| k-means | Needs k; spherical clusters; no noise label |
| DBSCAN | Single density threshold |
| Permutation importance only | No interaction values |
| LIME | Less stable for tabular trees |

## Consequences

- + No k to choose, handles noise
- + Interactions quantified
- − SHAP version coupling (fallback documented)

## Verification / compliance

Unit tests on synthetic clusters; multi_mode_6d recovery.
