# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/);
versioning: [Semantic Versioning 2.0.0](https://semver.org/) (policy in `docs/33`).

## [Unreleased]

### Added

- Warehouse map export, Gazebo reference map, nominal path artefacts, and map alignment tooling (T-092).
- Verified TB4 Nav2 topic map (`ros_ws/src/roboprobe_ros/config/topics.yaml`), JSON Schema, and evidence capture script (T-091).
- Playwright E2E harness and journeys (T-117, T-118, T-114): compose-backed global setup with
  seeded warehouse campaign, axe helper and page objects, journey specs, `e2e.yml`, Lighthouse
  nightly gate, and `size-limit` bundle budget in `build-web`.
- Reproducible headless Gazebo and Nav2 warehouse measurements with a one-worker laptop recommendation (T-090).
- Nightly API load test (T-106) checks endpoint p95 with a 10,000-run PostgreSQL seed and uploads the Locust CSV and runs-list query plan.
- Campaign scalability harness (T-130) measures real worker throughput, queue latency, and PostgreSQL health.
- Dashboard polish (T-113a/b, T-115): Spaces list with YAML view and validation,
  Workbench worker table, Settings (session token, theme, number locale, SSE reconnect),
  report export with sandboxed preview route, and global keyboard shortcuts dialog.
- Web production image (T-116): read-only nginx-unprivileged SPA, runtime `/config.json`,
  CSP and security headers, and a Compose `app` profile that starts the authenticated API,
  workers and dashboard with same-origin SSE.
- RoboProbe ROS package (T-093a) loads episode parameters and topic QoS, provides seeded
  node utilities, and checks vendored numerical modules against the backend source.
- Jazzy lidar relay (T-093b) applies seeded Gaussian noise and dropout and publishes beam counters.
- Jazzy depth relay (T-093c) applies seeded low-light dropout and radial range noise to
  PointCloud2 frames while preserving their timestamps and frames of reference.
- Opt-in experiment API launch atomically creates the planned campaign matrix and runs it
  through the orchestrator and workers (T-084a).
- Casebook and Insights (T-110a/b): filter and edit analyzed failure modes, replay or export
  representative scenarios, and compare SHAP importance with GP rankings and cross-validation.
- Analysis and reporting API follow-through (T-082b/c, T-084a): cached, anchored risk
  slices, campaign bundle jobs, durable report state and conflict-safe experiment notes.
- Trials comparison charts for recorded mode discoveries, per-cell metric samples, and
  censored time to first failure, plus HTML report export (T-112b, #181).
- Shared seed datasets (T-107, #159): a PostgreSQL fixture with 60 warehouse runs, three
  failure modes, medoid traces and seven API responses, plus a 10,000-run benchmark generator.
- Trace and artifact transport (T-081e): event-preserving JSON downsampling, original
  Parquet downloads, confined streamed attachments with digest ETags, and rejected-path logs.
- Dashboard foundation (T-085b/c/d): Field Notebook navigation, lazy feature routes,
  persisted Paper/Night Shift themes, runtime config, generated typed API hooks, session-scoped
  bearer auth, ETag-aware mutations and SSE reconnect/resume with query-cache updates.

- Campaign creation and Idempotency-Key responses now commit together, including `start: true`;
  filtered campaign pages use stable creation-time cursors and aggregated counters. Selection
  snapshots are restored during execution, and uploaded campaign spaces retain their pins.

- Campaign/run API completion (T-081b/c/d): entered request transactions, shared CLI/API
  validation and snapshots, idempotent creation, lifecycle warnings, mode-discovery progress,
  validated manual runs with derived seeds, and filtered stable SQL keyset pagination.

- Catalogue API completion (T-081a, #146): bounded YAML/JSON uploads, semantic space
  validation with JSON pointers, idempotent registration, immutable validated SUT profiles,
  and shared CLI catalogue services.

- kinematic2d calibration (T-034): tuned `kinematic2d_v1` + `oakd_k2d_v1`, sensor-informed
  replanning, canonical GT scenarios in `configs/reference/k2d_gt_canonical.yaml`, and acceptance
  test `test_calibration.py`.
- k2d reference set CLI (T-103): `roboprobe reference generate|label`, Parquet export + manifest
  hash for MET-02/MET-08 (`experiments.reference_set.*`).

- M7 REST API (T-081/082/084): `/api/v1` CRUD for spaces, SUT profiles, campaigns (lifecycle
  commands), runs, artifacts, failure modes, importance/risk, experiments, reports, and workers.
  Bootstrap wires `CampaignService` and analysis jobs; committed OpenAPI snapshot includes the new
  routes.
- `make backup` / `make restore` (`scripts/backup.sh`, `scripts/restore.sh`): timestamped `pg_dump -Fc` plus a
  zstd artefact archive with a SHA256 manifest. `BACKUP_RETENTION` (default 7) caps how many copies are kept.
  Restore refuses a non-empty database unless `--force` is passed, then runs `db upgrade` and `artifacts verify`.
- Observability profile (T-125, T-126): `make observability` starts digest-pinned Prometheus, Grafana
  (anonymous Viewer, admin password from a secret file) and an OTLP collector + Jaeger.
  Optional tracing (`roboprobe[otel]`) exports spans only when `observability.otlp_endpoint` is set.
  Compose ports: `ROBOPROBE_GRAFANA_PORT`, `ROBOPROBE_PROMETHEUS_PORT`, `ROBOPROBE_JAEGER_PORT`.
- SSE outbox hub and `GET /api/v1/events` (T-083a/b): LISTEN on `database.notify_channel` with poll
  recovery, per-subscriber queues that drop the oldest event and emit `resync` on overflow, and
  `Last-Event-ID` resume. New settings: `api.sse.poll_interval_s`, `queue_size`, `batch_size`,
  `reconnect_initial_s`, `reconnect_max_s`, `connect_timeout_s`. Metrics: `roboprobe_sse_clients`,
  `roboprobe_sse_reconnects_total`.
- Release tooling (T-119, T-124): `scripts/release_check.py` rejects a tag whose version does not
  match `backend/pyproject.toml`, `web/package.json`, and `package.xml` when the ROS package exists,
  or whose changelog section is missing. `.github/workflows/images.yml` builds the backend image
  (web and Gazebo when their Dockerfiles exist), scans it with Trivy, and attaches an SBOM.
  `.github/workflows/release.yml` runs that check, publishes images, and opens the GitHub Release.
- Security suite (T-109): `backend/tests/security/` maps each doc 31 threat to a test, and
  `scripts/check_security_map.py` fails CI when a `TM-xx` row is missing from
  `docs/evidence/security-tests.md`. Constraint literal exponents above
  `scenario.constraint_max_literal_exponent` and YAML alias bombs above `scenario.yaml_max_aliases`
  are rejected.
- Weekly mutation testing (T-131): `mutmut` on `selection/` and `oracles/` via
  `.github/workflows/mutation.yml` (schedule + manual, not a pull-request check). Kill rate is
  written to the job summary and an HTML artifact.
- Compose `orchestrator` and scalable `worker-k2d` services on the `core` profile (`ROBOPROBE_K2D_REPLICAS`,
  `/healthz` checks) and `make demo` for the 50-run `warehouse_v1` S-PROBE campaign
  (`configs/campaigns/k2d_demo_50.yaml`). Re-registering the space is a no-op.
- OpenAPI snapshot (T-084b): `make openapi` writes `api/openapi.json` from `create_app`. CI job
  `openapi-check` fails on drift and, once the snapshot is on the base branch, runs `oasdiff breaking`.
  Nightly `api-fuzz.yml` runs Schemathesis against the served API.
- Experiment configs EXP-01…EXP-07 (T-104): `configs/experiments/` plus the d=8 and
  doubled-lidar-noise warehouse spaces. Each file records the frozen S-PROBE pre-registration hash.
- The experiment CLI registers its SUT profile on a fresh database and isolates inline campaign
  heartbeats. The analytical multi-mode arm reports canonical mode counts and discovery AUC
  from observed failures (T-105a).
- API foundation (T-080a–d): FastAPI `create_app` with CORS/GZip, `/health/live|ready`, `/api/v1/meta`,
  `/metrics`, RFC 9457 `problem+json` (`docs/errors.md`), optional bearer auth (constant-time; required
  off-loopback), cursor pagination + ETag/`If-Match` helpers, Idempotency-Key store + Alembic
  `0002_idempotency_keys`, and `roboprobe api`. New settings: `api.error_type_base`, `api.cursor_secret`.
- Pins and sub-spaces (T-025): `ScenarioSpace.with_pins` and `roboprobe.scenario.pins.validate_pins`. Pinned parameters
  leave `params`/`dim` but keep the space id and version; `make_scenario` re-inserts them, so the hash includes them.
- Perception and friction models (T-031b): `roboprobe.perturbation.perception.PerceptionModel` (P3 depth degradation:
  η, `p_valid`, `σ_d`, `r_max`; constants in versioned `configs/perception/oakd_lowlight_v1.yaml`) and
  `roboprobe.perturbation.friction` (`traction`, `apply_slip`, P5).
- Scenario hashing (T-024): `roboprobe.scenario.hashing` (`canonical_json`, `content_hash`, `scenario_hash`) with
  golden hashes, and `ScenarioSpace.make_scenario` / `nominal()`; space versions and SUT config hashes now use the
  same public canonicaliser (values unchanged).
- Samplers (T-023): `roboprobe.scenario.samplers` with the `Sampler` protocol, `UniformSampler`, `PriorSampler`
  (prior inverse-CDF, scale-aware), `LatinHypercubeSampler` (random-cd), resumable scrambled `SobolSampler` and
  `GridSampler` (+ `for_budget`). The SciPy floor is raised to 1.15 for the `rng=` API.
- Unit-hypercube normalisation (T-021): `roboprobe.scenario.normalize` and `ScenarioSpace.to_unit/from_unit`
  (+ batch variants) for linear, log, int (bin centres) and categorical parameters per docs/06 §4.1, with
  Hypothesis round-trip properties (10 000 examples each). New log event `scenario.unit_clipped`.
- Web helpers (T-086c): `web/src/lib/format.ts` for locale-aware display formatting (`formatValue` with unit
  symbols, `formatLux` with significant digits, `formatDuration`, `formatRelative`, `formatPValue`, `formatA12`; tunables
  in `formatConfig`), and `web/src/lib/keyboard.ts` (`KeyboardManager` / `registerShortcut`) for single keys and `g b`
  chords. The chord timeout is set in `keyboardConfig`, form fields and contenteditable are ignored, conflicts are detected,
  and `list()` feeds the `?` dialog.
- Trace Parquet I/O (T-018): `roboprobe.backends.trace_io` with `write_trace`/`read_trace` (schema v1, zstd, units
  in field metadata, goal/meta as file metadata), `validate_trace` for sample-rate and gap checks, and an optional
  `Trace.rtf` column. Adds the `pyarrow-stubs` dev dependency.
- Perturbation models (T-031a): `roboprobe.perturbation.lidar` (`apply_lidar_noise` P4, `apply_dropout` P8; pure,
  seeded, NumPy-only) and `roboprobe.perturbation.delay.CommandDelayBuffer` (P6 time-indexed FIFO), shared with the ROS nodes.
- Ray casting (T-030b): `roboprobe.geometry.raycast` with `BeamSpec`, `GridRayCaster` and `cast` — vectorised
  half-cell marching with exact cell-entry refinement, analytic rectangles (optionally ignored for the lidar), ranges
  clipped to `[r_min, r_max]`; benchmark gate in `tests/benchmark/thresholds.yaml`.
- SUT profiles (T-016): `roboprobe.scenario.sut_profile.load_sut_profile()` (strict YAML, `schemas/sut_profile.schema.json`,
  per-backend typed config, id = file name, `provisional` keys rejected when strict) with a stable `config_hash`;
  `configs/sut_profiles/k2d_default.yaml` and `tb4_nav2_default.yaml`.
- Geometry kernel (T-030a): `roboprobe.geometry` with circle/polygon footprints, `OccupancyGrid` (world↔cell, SciPy
  EDT distance field), exact point/segment/rectangle/polygon distances and vectorised `min_obstacle_distance`;
  NumPy/SciPy only so the ROS package can vendor it. Adds `scipy-stubs` to the dev extra.
- Web design tokens (T-085a): `web/src/styles/tokens.json` holds the light and dark themes plus the font, space,
  radius and motion tokens, rendered to `tokens.css` by `pnpm gen:tokens` (staleness checked in `pnpm lint`) and
  copied to the report theme. Also: self-hosted IBM Plex WOFF2 fonts (OFL, `web/public/fonts/`), `base.css` (reset,
  paper grid, focus ring, reduced motion), A4 `print.css`, `applyTheme` for `data-theme`/`system`, a WCAG contrast
  test over `tokens.pairs.json`, and Stylelint (no raw hex or px font sizes outside tokens).
- Compose `core` stack (T-005b): `docker/compose.yaml` with digest-pinned Postgres 17 (`db_password` Docker secret,
  `pg_isready` health check, `pgdata` volume), one-shot `migrate` on the backend image (placeholder `--version`), the
  `x-backend` anchor, and a `dev`-profile loopback forwarder publishing Postgres; `make up` / `down` / `db-up` / `logs` /
  `ps`; `make setup` generates `secrets/db_password`; new compose variable `ROBOPROBE_DB_PORT`.
- Materialisation helpers (T-028): `roboprobe.scenario.materialize.render_template` (sandboxed Jinja2,
  `StrictUndefined`, byte-identical output) and `place_obstacle` (arc-length placement with left normal and
  tangent-aligned yaw, docs/06 §3.2) shared by both backends.
- Repository governance (T-132): `main` ruleset (PR-only, required CI checks, linear history, no force push, conversation
  resolution), squash-only merges with auto-delete and auto-merge, and the "RoboProbe backlog" project board; documented in docs/20 §3.1.
- Backend container image (T-005a): `docker/backend.Dockerfile` — multi-stage uv build (`api`, `worker`, `ml` extras,
  CPU-only torch), digest-pinned `python:3.12-slim` runtime, non-root uid 10001, `ENTRYPOINT ["roboprobe"]`, OCI labels
  from build args, `/data/artifacts` volume; allow-list `.dockerignore`.
- Constraint evaluator (T-022): `roboprobe.scenario.constraints` compiles space constraints with a restricted AST
  whitelist into vectorised NumPy closures (never `eval`), rejects disallowed constructs at load time, and adds
  `rejection_sample` plus the `scenario.constraint_max_attempts` setting; `ScenarioSpace.is_feasible` now applies
  the constraints.
- Supply-chain CI (T-006c): `.github/dependabot.yml` (weekly uv, npm, GitHub Actions and Docker updates, minor/patch
  grouped). `ci.yml` gains `security` (pip-audit and pnpm audit gated at high/critical through `scripts/check_audit.py`
  with OSV severity lookup and a justified `scripts/audit_ignore.txt`, plus gitleaks) and `license-check`
  (`scripts/check_licenses.py` evaluating SPDX expressions against `scripts/allowed_licenses.txt`).
- Metrics and health (T-004b): `roboprobe.core.metrics_registry` defines every docs/21 §5.2 metric in a dedicated
  registry (Null Object when `observability.metrics_enabled=false`); `roboprobe.core.health` with `run_checks` and an
  internal `/healthz` (200/503 JSON) + `/metrics` server for workers and the orchestrator.
- `roboprobe config show [--sources]` (T-003b): every resolved key as a dotted path, secrets masked, source per key
  (`cli`, `env`, `.env`, `toml:<path>`, `secrets`, `default`), `--json` for scripts; `config.loaded` event logs sources only.
  `load_settings(config_file=...)` lets the global `--config` flag select the TOML file.
- Scenario spaces (T-020b): `roboprobe.scenario.space` (`ParameterSpec`, `PriorSpec`, `Constraint`,
  `ScenarioSpace.from_yaml/from_text`) with schema plus semantic validation and JSON-pointer errors (`SPACE_INVALID`).
  The space version is a content hash that ignores comments and formatting. Ships `configs/scenario_spaces/warehouse_v1.yaml`
  (P1–P8, d = 6 by default, 8 with P7/P8 enabled).
- CI pipeline (T-006a): `.github/workflows/ci.yml` with `lint` (ruff, mypy, import-linter, ESLint, Prettier, tsc and a
  tier-marker guard), `test-backend` (ubuntu/macos, unit+property+contract with the coverage gate), `test-integration`
  (PostgreSQL 17 service), `test-web` (Vitest + coverage), `build-web` and `config-docs-check`. Actions are pinned by SHA, with
  least-privilege permissions, JUnit and coverage job summaries and artefacts; shared setup lives in `.github/actions/setup-{backend,web}`.
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

- Risk Atlas loads Plotly for the full heatmap and static previews, with responsive uncertainty hatches and keyboard-accessible probe controls (T-111a).
- Risk atlas off-axis controls now query and update the share URL after edits settle (T-111b).
- The Bench reserves space while campaigns load. The campaign wizard prevents repeated
  submission, links validation errors to their fields, and exports YAML accepted by
  `roboprobe campaign create -f`.
- `.env.example` and `roboprobe.example.toml` now list every setting (commented out, with defaults and
  descriptions) instead of a hand-picked subset.
- Docs: fixed Markdown that rendered incorrectly (paragraphs swallowed into tables, unescaped `|` in table code spans,
  missing blank lines, bare URLs) and normalised formatting to pass markdownlint.
- README rewritten as a full project landing page; `CONTRIBUTING.md` and `SECURITY.md` expanded;
  PR template renamed to `.github/PULL_REQUEST_TEMPLATE.md`.
- The Console cancellation dialog wraps keyboard focus in both directions and returns focus
  to the trigger when dismissed.

### Fixed

- Embed the API comparison payload in offline experiment reports and surface restart-interrupted
  report jobs as errors (T-084a).
- Casebook interaction checks, replays, and Atlas manual probes run after campaign completion.
  New confirmation evidence keeps case edits and membership intact (T-110a, #176; T-111b, #179).
- The campaign Console loads scenario bounds for run condition strips and shows selector
  predictions when the strategy supplies them (T-088b, #172).
- Provide worker heartbeat age and current run with opaque IDs and pagination cursors. Apply
  the configured report concurrency to the API executor (T-084a).

## [0.0.1] - 2026-11-19

### Added

- Complete Phase-0 specification: vision, PRD, SRS, personas & use cases, architecture (C4), module design,
  scenario schema, selection algorithms, failure taxonomy, analysis & risk mapping, simulator integration,
  data model, API, dashboard UX/UI, workflows, tech stack, ADR-0001…ADR-0016, repository standards,
  dev environment, testing strategy, evaluation plan, CI/CD, security/reproducibility/observability,
  roadmap with task breakdown, risks, glossary, references, configuration reference, traceability matrix,
  deployment guide, operations runbook, threat model, engineering process, versioning policy,
  design principles, and document templates.
