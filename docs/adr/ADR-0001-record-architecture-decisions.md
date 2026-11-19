# ADR-0001: Record architecture decisions

| Field | Value |
|-------|-------|
| Status | Accepted |
| Date | 2026-11-19 |
| Deciders | Priyanshu Jha (owner) |
| Supersedes / Superseded by | – |

## Context

The project will be implemented mostly by AI coding agents across many sessions. Decisions made in one session must not be silently reversed in another, and the reasoning must be available to the student owner and evaluators.

## Decision

We record every significant, hard-to-reverse decision as an ADR in `docs/adr/` using the template in `docs/templates/adr-template.md` (context, decision, alternatives, consequences). ADRs are immutable once Accepted; a change is a new ADR that supersedes the old one. A decision is 'significant' if it affects module boundaries, a public interface, a dependency, data formats, or deployment.

## Alternatives considered

| Option | Assessment |
|--------|-----------|
| Wiki pages | Drift from code; not reviewed in PRs |
| Comments in code | Scattered; no alternatives recorded |
| No records | Agents re-litigate decisions |

## Consequences

- + Reviewable in PRs, versioned with code
- + Agents can check constraints before coding
- − Small overhead per decision

## Verification / compliance

PR template asks 'Does this change a decision? Link/create ADR'. `docs/adr/README.md` index must list every file (checked by a CI script).
