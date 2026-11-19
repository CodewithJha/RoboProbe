# Contributing to RoboProbe

First off, thank you for considering a contribution! RoboProbe aims to become a useful, rigorous,
open-source tool for discovering failures of autonomous robots in simulation. Every contribution —
a typo fix, a review, a question, a design critique or code — helps.

> **Project phase: design / pre-alpha.** The repository currently contains the complete specification
> (`docs/`). Implementation starts with milestone **M1**. Until then the most valuable contributions are
> **reviews of the design documents**, issues pointing out gaps or inconsistencies, and discussion of the
> algorithms and evaluation plan.

By participating you agree to follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## Table of contents

1. [Ways to contribute](#1-ways-to-contribute)
2. [Before you start](#2-before-you-start)
3. [Development workflow](#3-development-workflow)
4. [Branch & commit conventions](#4-branch--commit-conventions)
5. [Pull request process](#5-pull-request-process)
6. [Documentation contributions](#6-documentation-contributions)
7. [Coding standards (summary)](#7-coding-standards-summary)
8. [Good first issues](#8-good-first-issues)
9. [Licensing](#9-licensing)

## 1. Ways to contribute

- **Review the spec** — read a document in `docs/` and open a *Documentation* issue for anything unclear, wrong or inconsistent.
- **Report bugs** — use the *Bug report* template (once code exists).
- **Propose features** — use the *Feature request* template; larger ideas become an RFC.
- **Implement tasks** — pick a `T-NNN` task from [`docs/22`](docs/22-roadmap-and-implementation-plan.md) (from M1 on).
- **Review pull requests** — reviews following [`docs/32` §5](docs/32-engineering-process-code-review-dor-dod.md) are hugely appreciated.

## 2. Before you start

1. Read [`docs/00-index.md`](docs/00-index.md) and the reading path for your area.
2. For code: also read [`docs/16`](docs/16-repository-structure-and-coding-standards.md) (standards), [`docs/34`](docs/34-design-principles-patterns-and-conventions.md) (design principles), [`docs/18`](docs/18-testing-strategy-and-qa.md) (testing) and [`docs/27`](docs/27-configuration-reference.md) (configuration).
3. For anything non-trivial, **open or comment on an issue first** so work isn't duplicated.
4. Changes that add a module, alter a public interface/schema, add a notable dependency or change the evaluation methodology need an **RFC** ([template](docs/templates/rfc-template.md)) and usually an **ADR**.
5. Only free and open-source dependencies are accepted — never a paid service or API.

## 3. Development workflow

> The tooling below becomes available with task T-001 (milestone M1).

```bash
# one-time
git clone https://github.com/<you>/RoboProbe.git && cd RoboProbe
git remote add upstream https://github.com/CodewithJha/RoboProbe.git
cp .env.example .env
make setup            # uv sync (Python 3.12), pnpm install, pre-commit install

# every change
git switch main && git pull upstream main
git switch -c feat/T-041-worker-heartbeat
# write failing tests first, then the implementation
make lint typecheck test      # must be green (lint includes the architecture contracts)
make docs-check               # if you touched docs (markdownlint, Mermaid, links)
git commit                    # Conventional Commit message
git push origin HEAD          # open a PR against CodewithJha/RoboProbe:main
```

Local stack: `make up` (Docker Compose `core` profile) · `make demo` (sample campaign) · Gazebo: [`docs/17`](docs/17-dev-environment-and-docker.md).

## 4. Branch & commit conventions

- **Branches:** `feat/T-NNN-short-name`, `fix/<issue>-short-name`, `docs/<topic>`, `chore/…`, `refactor/…`, `spike/…`.
- **Commits:** [Conventional Commits 1.0](https://www.conventionalcommits.org/): `type(scope): summary` in the imperative, ≤ 72 chars.
  Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`, `revert`. Scope = package or doc (`selection`, `oracles`, `api`, `web`, `docs`).
  Body: what and why; footer: `Refs: T-041, FR-RUN-002` / `Closes #123`. Breaking changes: `!` after the type and a `BREAKING CHANGE:` footer.
- Keep commits focused; we squash-merge, so the PR title becomes the final commit message.

## 5. Pull request process

1. One task/topic per PR; ideally ≤ 400 changed lines (excluding lock/generated files).
2. Fill in the [PR template](.github/PULL_REQUEST_TEMPLATE.md): links to task/requirements, test evidence, screenshots for UI, risk & rollback.
3. CI must be green before review (once CI exists, from T-006).
4. A maintainer reviews against the checklist in [`docs/32` §5](docs/32-engineering-process-code-review-dor-dod.md); respond to every comment.
5. Definition of Done ([`docs/32` §3](docs/32-engineering-process-code-review-dor-dod.md)) must be satisfied: tests, docs, config reference, traceability, CHANGELOG.
6. The maintainer squash-merges. Thank you!

## 6. Documentation contributions

- Docs are Markdown in `docs/`, numbered with **stable IDs** (never renumber; add new docs at the end and list them in `docs/00-index.md` and the README).
- Requirement/ID prefixes (`FR-`, `NFR-`, `PR-`, `T-`, `ADR-` …) are defined in `docs/00` §3 — never reuse or renumber an ID.
- Diagrams: Mermaid only; quote node labels, avoid unescaped parentheses/semicolons; validate with `npx @mermaid-js/mermaid-cli -i file.mmd -o out.svg` (or `make docs-check`).
- `make docs-check` (CI: `.github/workflows/docs.yml`) runs markdownlint (`.markdownlint.jsonc`), renders every Mermaid block,
  checks relative links and `#anchors` with [lychee](https://lychee.cli.rs/) (`lychee.toml`; `LINKS_ONLINE=1` adds external URLs)
  and verifies the ADR indexes. It needs Node.js (for `npx`), Python 3 and lychee or Docker; run one check with
  `make docs-check DOCS_CHECKS=links`. Tables with `|` inside code spans must escape it as `\|`.
- Decisions: a changed decision needs a **new ADR** superseding the old one ([template](docs/templates/adr-template.md)).
- Use English, SI units, and RFC 2119 keywords for requirements.

## 7. Coding standards (summary)

Python 3.12 · `ruff` + `mypy --strict` · Google docstrings with `Implements: <IDs>` · no hard-coded tunables (typed settings, `docs/27`) · injected RNG and clock · layered hexagonal architecture enforced by import-linter · TypeScript strict + ESLint/Prettier · tests first. Full details: [`docs/16`](docs/16-repository-structure-and-coding-standards.md), [`docs/34`](docs/34-design-principles-patterns-and-conventions.md).

### Architecture contracts

`make lint` runs [import-linter](https://import-linter.readthedocs.io/) (`lint-imports`) with the contracts in
`backend/pyproject.toml` (`[tool.importlinter]`), which encode the layering of [`docs/16` §2](docs/16-repository-structure-and-coding-standards.md#2-layering-enforced):

| Contract id | Rule |
|-------------|------|
| `layers` | `api \| cli` → `runner`, `experiments`, `reporting` → domain (`selection`, `oracles`, `analysis`, `risk`, `metrics`, `scenario`) → kernel (`core`, `geometry`, `perturbation`); never upwards. |
| `domain-independence` | Domain and kernel never import `roboprobe.store`, `roboprobe.backends`, `roboprobe.api`, `roboprobe.bootstrap`, `fastapi`, `sqlalchemy` or `rclpy`, directly or indirectly. |
| `adapters-wired-in-bootstrap` | Application and interface packages never *directly* import `roboprobe.store` / `roboprobe.backends`; concrete adapters are wired in `roboprobe.bootstrap`. |
| `adapters-point-inward` | `store` and `backends` depend only on domain and kernel, never on application, interface or bootstrap. |
| `services-never-import-bootstrap` | `runner`, `experiments` and `reporting` receive their dependencies by injection and never import `roboprobe.bootstrap`. |

A failure names the broken contract and the offending import chain, e.g.

```text
Domain and kernel never depend on infrastructure, interfaces or frameworks BROKEN
-   roboprobe.selection -> sqlalchemy (l.5)
```

Read it as *importer → imported (line)*. Fix the design rather than the contract: depend on a Protocol in
`roboprobe.core` (or the module's `base.py`) and inject the concrete class from `roboprobe.bootstrap`.
Changing a contract needs an ADR. To check a contract locally, temporarily add the forbidden import
(e.g. `import sqlalchemy` in `roboprobe/selection/__init__.py`), run `make lint`, and revert.

## 8. Good first issues

Look for the `good first issue` label. Good starting points that need little context:

- Documentation review of a single doc (consistency of IDs, broken links, unclear sentences).
- Golden-trace fixtures for an oracle (`docs/08` §7) — once M3 starts.
- Analytic benchmark functions (`docs/07` §9, task T-052).
- Small UI components with clear specs (`ConditionStrip`, `RobustnessBar` — `docs/13` §6).

## 9. Licensing

RoboProbe is [MIT-licensed](LICENSE). By submitting a contribution you agree that it is licensed under the
MIT License and that you have the right to submit it.
