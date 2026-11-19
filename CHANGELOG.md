# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/);
versioning: [Semantic Versioning 2.0.0](https://semver.org/) (policy in `docs/33`).

## [Unreleased]
### Added
- Test infrastructure (T-017): Hypothesis `dev`/`ci`/`nightly` profiles (`HYPOTHESIS_PROFILE`), `tests/factories.py`
  domain builders, `tests/fakes/` package, PostgreSQL 17 fixtures (`ROBOPROBE_TEST_DATABASE_URL` or Testcontainers) with per-test rollback.
- JSON Schemas (T-020a): `schemas/{scenario_space,scenario,task,campaign,experiment}.schema.json`
  (Draft 2020-12, `additionalProperties: false`) with valid/invalid fixtures. The tests validate the examples
  in docs 06/07/12/19 directly from the Markdown sources.
- CLI skeleton (T-008): `roboprobe` console script (Typer/Rich) with `--version`, `--config`, `--log-level`,
  `--json`; append-only `COMMAND_GROUPS` registration; exit codes 0/1/2/3 per docs/05 §11 (`ConfigError`/`ValidationError` → 2).
- Seed derivation (T-002c): `roboprobe.core.seeding` with `stable_hash`, `derive_seed`, `make_rng`,
  `random_campaign_seed` and the canonical stream keys (docs/21 §3); golden seeds pinned as a reproducibility contract.
- Architecture contracts (T-009): five import-linter contracts (`layers`, `domain-independence`,
  `adapters-wired-in-bootstrap`, `adapters-point-inward`, `services-never-import-bootstrap`) enforcing docs/16 §2, run by `make lint`;
  how to read a failure is documented in `CONTRIBUTING.md`.
- Backend monorepo skeleton (T-001): `backend/` uv project for package `roboprobe` with extras `ml`, `worker`,
  `api`, `dev` and a committed `uv.lock` (CPU-only PyTorch index); layered sub-package layout from docs/16 §1;
  ruff, mypy `--strict`, pytest markers and coverage gate configuration; root `Makefile`
  (`setup`, `lint`, `typecheck`, `test`, `test-fast`, `test-cov`), `.pre-commit-config.yaml`, `.env.example`
  and `roboprobe.example.toml`.
- Shared core types (T-002a): `roboprobe.core.types` with the normative enums, frozen value objects
  (`Scenario`, `Proposal`, `Observation`, `OracleResult`, `RunOutcome`, `TaskSpec`, `SutProfile`, `Pose2D`)
  and the validated, read-only columnar `Trace` (docs/05 §1).
- Injectable clock (T-002d): `roboprobe.core.clock` with the `Clock` protocol, `SystemClock` (tz-aware UTC)
  and the deterministic `FakeClock` (`advance`, instant `sleep`).
- `web/` dashboard skeleton: Vite 6 + React 19 + TypeScript (strict), ESLint (typescript-eslint strict,
  react-hooks, jsx-a11y, `dangerouslySetInnerHTML` ban) + Prettier, Vitest + Testing Library, pnpm 9 (T-007).
- Error hierarchy (T-002b): `roboprobe.core.errors` with `RoboProbeError` and its subclasses (docs/34 §5),
  stable `ErrorCode` values including every API envelope code (docs/12 §1.1), picklable errors with
  read-only `context`, and `is_transient()` for retry decisions.
- Typed layered settings (T-003a): `roboprobe.core.settings` package with the full docs/27 §4.1–4.10 tree,
  `load_settings()` (CLI > env > `.env` > TOML > secret files > defaults, fail-fast `ConfigError` listing every
  problem) and `explain_sources()`.
- Structured logging (T-004a): `roboprobe.core.logging` with `configure_logging()` (JSON/console, `ts`, `level`,
  `logger`, `service`, `version`), `bind_context()` for correlation ids, secret redaction and the `EVENTS`
  catalogue enforced by an AST test.
- Open-source community files: `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `SUPPORT.md`, `GOVERNANCE.md`,
  `CITATION.cff`, `.editorconfig`, `.github/CODEOWNERS`, issue forms (bug, feature, docs) and `config.yml`.
### Changed
- README rewritten as a full project landing page; `CONTRIBUTING.md` and `SECURITY.md` expanded;
  PR template renamed to `.github/PULL_REQUEST_TEMPLATE.md`.

## [0.0.1] - 2026-11-19
### Added
- Complete Phase-0 specification: vision, PRD, SRS, personas & use cases, architecture (C4), module design,
  scenario schema, selection algorithms, failure taxonomy, analysis & risk mapping, simulator integration,
  data model, API, dashboard UX/UI, workflows, tech stack, ADR-0001…ADR-0016, repository standards,
  dev environment, testing strategy, evaluation plan, CI/CD, security/reproducibility/observability,
  roadmap with task breakdown, risks, glossary, references, configuration reference, traceability matrix,
  deployment guide, operations runbook, threat model, engineering process, versioning policy,
  design principles, and document templates.
