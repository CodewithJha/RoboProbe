# GitHub issue backlog

The task plan in [doc 22](22-roadmap-and-implementation-plan.md) is tracked as GitHub issues. Each milestone has an **epic** (tracking issue) and small single-responsibility **task** issues. Every task is independently mergeable and lists its scope, implementation guidance, configuration keys, acceptance criteria, required tests, dependencies (*Blocked by* / *Blocks*), the files it owns, and deep links into these design docs.

| Milestone | Epic | Tasks | Due (indicative) |
|---|---|---|---|
| [M1 — Foundation](https://github.com/CodewithJha/RoboProbe/milestone/1) | [#1](https://github.com/CodewithJha/RoboProbe/issues/1) | 20 | 2026-11-27 |
| [M2 — Scenario + kinematic2d](https://github.com/CodewithJha/RoboProbe/milestone/2) | [#2](https://github.com/CodewithJha/RoboProbe/issues/2) | 27 | 2026-12-04 |
| [M3 — Oracles + runner + store](https://github.com/CodewithJha/RoboProbe/milestone/3) | [#3](https://github.com/CodewithJha/RoboProbe/issues/3) | 40 | 2026-12-11 |
| [M4 — Baselines + metrics + experiments](https://github.com/CodewithJha/RoboProbe/milestone/4) | [#4](https://github.com/CodewithJha/RoboProbe/issues/4) | 10 | 2026-12-18 |
| [M5 — Intelligent selection](https://github.com/CodewithJha/RoboProbe/milestone/5) | [#5](https://github.com/CodewithJha/RoboProbe/issues/5) | 15 | 2027-01-01 |
| [M6 — Analysis + risk](https://github.com/CodewithJha/RoboProbe/milestone/6) | [#6](https://github.com/CodewithJha/RoboProbe/issues/6) | 17 | 2027-01-08 |
| [M7 — API](https://github.com/CodewithJha/RoboProbe/milestone/7) | [#7](https://github.com/CodewithJha/RoboProbe/issues/7) | 19 | 2027-01-15 |
| [M8 — Dashboard](https://github.com/CodewithJha/RoboProbe/milestone/8) | [#8](https://github.com/CodewithJha/RoboProbe/issues/8) | 28 | 2027-01-29 |
| [M9 — Gazebo backend](https://github.com/CodewithJha/RoboProbe/milestone/9) | [#9](https://github.com/CodewithJha/RoboProbe/issues/9) | 16 | 2027-02-12 |
| [M10 — Evaluation](https://github.com/CodewithJha/RoboProbe/milestone/10) | [#10](https://github.com/CodewithJha/RoboProbe/issues/10) | 15 | 2027-02-26 |
| [M11 — Release 1.0](https://github.com/CodewithJha/RoboProbe/milestone/11) | [#11](https://github.com/CodewithJha/RoboProbe/issues/11) | 4 | 2027-03-05 |

**Total:** 211 task issues + 11 epics.

## Working the backlog

- Pick an open issue whose *Blocked by* issues are all closed. GitHub sub-issues and issue dependencies mirror the epic and *Blocked by* relationships.
- Task IDs (`T-NNN`, with letter suffixes for splits of a doc 22 task) appear in issue titles; use them in branch names and commit messages ([doc 16 §6](16-repository-structure-and-coding-standards.md), [AGENTS.md](../AGENTS.md) §4).
- Each issue lists the paths it owns. Shared registration files (`pyproject.toml` entry points, `cli/main.py`, `api/routers/__init__.py`, `web/src/router.tsx`, `docker/compose.yaml`, `.github/workflows/ci.yml`) are append-only, so parallel PRs do not conflict.
- Definition of Ready and Done: [doc 32](32-engineering-process-code-review-dor-dod.md).

## Labels

`type:*` (feature, chore, test, docs, infra, research, epic) · `area:*` (component) · `priority:P0`–`P3` · `size:XS`–`L` · `milestone:M1`–`M11` · `task` · `good first issue` · `help wanted`.

Filters: [good first issues](https://github.com/CodewithJha/RoboProbe/issues?q=is%3Aopen+label%3A%22good+first+issue%22) · [P0](https://github.com/CodewithJha/RoboProbe/issues?q=is%3Aopen+label%3Apriority%3AP0) · [M1 tasks](https://github.com/CodewithJha/RoboProbe/issues?q=is%3Aopen+milestone%3A%22M1+%E2%80%94+Foundation%22)
