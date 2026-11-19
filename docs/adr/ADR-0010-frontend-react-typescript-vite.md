# ADR-0010: React + TypeScript + Vite SPA with an original design system

| Field | Value |
|-------|-------|
| Status | Accepted |
| Date | 2026-11-19 |
| Deciders | Priyanshu Jha (owner) |
| Supersedes / Superseded by | – |

## Context

The concept suggests React. The dashboard is data-heavy (heatmaps, timelines), single-user and local. The user requires an original, unique visual design.

## Decision

React 19 + TypeScript (strict) + Vite; TanStack Query for server state; React Router; Radix UI primitives; CSS Modules with design tokens of the original 'Field Notebook' language (13 §1); Plotly.js partial bundle for analytical charts, custom SVG for signature components. Types generated from OpenAPI.

## Alternatives considered

| Option | Assessment |
|--------|-----------|
| Next.js | SSR not needed; adds server |
| Streamlit/Dash | Fast to prototype but limited UX control and real-time UX |
| Vue/Svelte | Fine, but concept and agent familiarity favour React |
| Tailwind + component kits | Tends toward generic look; tokens + CSS Modules keep the design original |

## Consequences

- + Strong typing end-to-end
- + Static build served by nginx
- − More code than Streamlit

## Verification / compliance

Vitest + Playwright + axe in CI; bundle budget.
