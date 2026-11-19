# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/);
versioning: [Semantic Versioning 2.0.0](https://semver.org/) (policy in `docs/33`).

## [Unreleased]

### Added

- `roboprobe config show [--sources]` (T-003b): every resolved key as a dotted path, secrets masked, source per key
  (`cli`, `env`, `.env`, `toml:<path>`, `secrets`, `default`), `--json` for scripts; `config.loaded` event logs sources only.
  `load_settings(config_file=...)` lets the global `--config` flag select the TOML file.
- Scenario spaces (T-020b): `roboprobe.scenario.space` (`ParameterSpec`, `PriorSpec`, `Constraint`,
  `ScenarioSpace.from_yaml/from_text`) with schema plus semantic validation and JSON-pointer errors (`SPACE_INVALID`).
  The space version is a content hash that ignores comments and formatting. Ships `configs/scenario_spaces/warehouse_v1.yaml`
  (P1–P8, d = 6 by default, 8 with P7/P8 enabled).
- Test infrastructure (T-017): Hypothesis `dev`/`ci`/`nightly` profiles (`HYPOTHESIS_PROFILE`), `tests/factories.py`
  domain builders, `tests/fakes/` package, PostgreSQL 17 fixtures (`ROBOPROBE_TEST_DATABASE_URL` or Testcontainers) with per-test rollback.
- Task loader (T-027): `roboprobe.scenario.task` (`load_task` with TBD guard and strict mode for provisional
  values, `load_nominal_path`, `time_limit_s`), `tasks/warehouse_delivery_v1.yaml` with a provisional goal and
  nominal path, `scripts/check_no_tbd.py`, and a strict YAML/JSON-Schema document helper (safe tags only,
  duplicate keys rejected, size limit, JSON-pointer errors). JSON Schemas ship inside the wheel as
  `roboprobe/schemas/`.

- JSON Schemas (T-020a): `schemas/{scenario_space,scenario,task,campaign,experiment}.schema.json`
  (Draft 2020-12, `additionalProperties: false`) with valid/invalid fixtures. The tests validate the examples
  in docs 06/07/12/19 directly from the Markdown sources.
- CLI skeleton (T-008): `roboprobe` console script (Typer/Rich) with `--version`, `--config`, `--log-level`,
  `--json`; append-only `COMMAND_GROUPS` registration; exit codes 0/1/2/3 per docs/05 §11 (`ConfigError`/`ValidationError` → 2).
- Seed derivation (T-002c): `roboprobe.core.seeding` with `stable_hash`, `derive_seed`, `make_rng`,
  `random_campaign_seed` and the canonical stream keys (docs/21 §3); golden seeds pinned as a reproducibility contract.
- Docs quality gate (T-006b): `make docs-check` / `scripts/check_docs.sh` runs markdownlint-cli2, a mermaid-cli
  render of every Mermaid block, lychee link and anchor checks and an ADR index check; `.github/workflows/docs.yml`
  runs it on Markdown changes, plus a weekly external link check.
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
- Configuration reference generator (T-003c): `scripts/gen_config_docs.py` renders docs/27 §4.1–4.10,
  `.env.example` and `roboprobe.example.toml` from the settings models; `make config-docs` /
  `make config-docs-check` (fails with a diff on drift); a pre-commit hook runs the check.
- Open-source community files: `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `SUPPORT.md`, `GOVERNANCE.md`,
  `CITATION.cff`, `.editorconfig`, `.github/CODEOWNERS`, issue forms (bug, feature, docs) and `config.yml`.

### Changed

- `.env.example` and `roboprobe.example.toml` now list every setting (commented out, with defaults and
  descriptions) instead of a hand-picked subset.
- Docs: fixed Markdown that rendered incorrectly (paragraphs swallowed into tables, unescaped `|` in table code spans,
  missing blank lines, bare URLs) and normalised formatting to pass markdownlint.
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
