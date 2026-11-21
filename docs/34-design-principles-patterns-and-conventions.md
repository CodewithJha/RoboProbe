# 34 — Design Principles, Patterns & Engineering Conventions

> Related: [04 Architecture](04-system-architecture.md) · [05 Module design](05-module-detailed-design.md) · [16 Standards](16-repository-structure-and-coding-standards.md) · [ADR-0015](adr/ADR-0015-typed-layered-configuration.md) · [ADR-0016](adr/ADR-0016-plugin-architecture-entry-points.md)

## 1. Quality goals that drive the design

| Goal | Design response |
|------|----------------|
| **Maintainability** | layered hexagonal architecture, small modules, strict typing, documented interfaces, high test coverage, ADRs |
| **Modularity** | eight modules with single responsibilities (M1–M8) communicating through typed data objects |
| **Extensibility** | ports + entry-point plugins for simulators, strategies, oracles, analyzers, stores |
| **Scalability** | stateless workers pulling from a DB queue; batch proposals; horizontal worker scaling across hosts; stateless API |
| **Deployability** | containers, env-based typed config, one-command `make up`, automated migrations, CI-built images |
| **Reproducibility** | seed tree, manifests, pure oracles, versioned semantics |
| **Testability** | dependency injection, fakes for every port, deterministic backend |

## 2. SOLID in RoboProbe

| Principle | Concrete application |
|-----------|---------------------|
| **S**ingle responsibility | `ScenarioSpace` knows parameters, not sampling policy; `VerdictEngine` combines oracles but computes no metric itself; `Worker` orchestrates execution but delegates simulation, judging and persistence |
| **O**pen/closed | new simulator/strategy/oracle = new class + entry point; core unchanged (10 §10) |
| **L**iskov substitution | every backend passes the same contract suite; `ReplayBackend` substitutes real backends in tests |
| **I**nterface segregation | small ports: `RunQueue` (claim/heartbeat/complete) separate from `RunRepo` (queries); `ArtifactStore` separate from repositories; read-only `HistoryProvider` for strategies |
| **D**ependency inversion | domain depends on Protocols in `roboprobe.core`/module `base.py`; adapters depend on domain, never the reverse (import-linter) |

## 3. Dependency injection & composition roots

- Constructor injection everywhere; no module-level singletons (except immutable constants and loggers).
- One composition root per process in `roboprobe.bootstrap`: `build_api(settings)`, `build_orchestrator(settings)`, `build_worker(settings)`, `build_cli(settings)`. They read settings once, construct adapters (engine, UoW factory, artefact store, backend, registries) and inject them.
- FastAPI dependencies (`Depends`) only adapt request scope to these factories (`get_uow`), never create infrastructure ad hoc.
- Plugin discovery: `importlib.metadata.entry_points(group=…)`; registry validates `id` uniqueness and API version (`PLUGIN_API_VERSION = 1`); unknown ids fail at startup with a list of available plugins.

```python
# roboprobe/bootstrap/worker.py (sketch)
def build_worker(settings: RoboProbeSettings) -> WorkerProcess:
    engine = make_engine(settings.database)
    uow_factory = SqlAlchemyUnitOfWorkFactory(engine)
    store = artifact_store_registry.create(settings.storage)
    backend = backend_registry.create(settings.worker.backend, settings.backends)
    verdicts = VerdictEngine(oracle_registry.create_all(settings.oracles))
    return WorkerProcess(backend=backend, uow_factory=uow_factory, artifact_store=store,
                         verdict_engine=verdicts, clock=SystemClock(), settings=settings.worker)
```

## 4. Patterns used (and where)

| Pattern | Where | Why |
|---------|-------|-----|
| Ports & Adapters | backends, store, queue | swap infrastructure |
| Strategy | `selection` (`S-*`), oracles | interchangeable algorithms |
| Template Method | `Strategy.propose` common pre/post-processing (dedupe, feasibility, rationale) around `_propose_impl` | enforce contract rules once |
| Registry + Plugin (entry points) | backends, strategies, oracles, analyzers, stores | extensibility |
| Repository + Unit of Work | `store` | transactional consistency, testable persistence |
| Transactional Outbox | `events` table + NOTIFY | reliable event delivery to SSE |
| State machine | campaign, run, worker, S-PROBE phases | explicit, testable lifecycles (transition tables, illegal transitions raise) |
| Factory | composition roots, materialisers | construction logic in one place |
| Builder | `ManifestBuilder`, `EpisodeConfig` | complex immutable objects |
| Specification | constraint evaluator, filters | composable predicates |
| Memento | `Strategy.state_dict/load_state_dict` | resumable campaigns |
| Observer (via events) | SSE hub, incremental analysis triggers | decoupled notifications |
| Value Object | `Scenario`, `Observation`, `OracleResult` (frozen) | immutability, hashing |
| Anti-corruption layer | Gazebo adapter translating ROS/Gazebo details into `Trace` | keep ROS out of the domain |
| Null Object | `NoopTracer`, `NullArtifactStore` (tests) | optional features without `if` chains |

## 5. Error handling conventions

- Hierarchy (in `roboprobe.core.errors`):
  `RoboProbeError` → `ConfigError`, `ValidationError` (domain), `NotFoundError`, `ConflictError` (invalid state transition), `BackendError` (→ `EpisodeLaunchError`, `EpisodeTimeoutError`), `OracleError`, `StrategyError` (→ `ModelFitError`), `StoreError` (→ `QueueError`), `PluginError`.
- Each error has a stable `code` (e.g. `CAMPAIGN_INVALID_TRANSITION`), human `message`, and structured `context` dict.
- **Where to catch:** at boundaries only — API exception handlers map errors to problem+json (12 §1.1); workers map backend errors to `INVALID` runs with `infra_error`; CLI maps to exit codes (05 §11). Domain code raises, never logs-and-swallows.
- Expected failures of the *robot* are **data** (verdicts), never exceptions.
- Retries: only for transient infrastructure (DB serialisation failure, Gazebo launch) with bounded exponential backoff (config `runner.retry.*`); never retry domain validation errors.
- `assert` only for internal invariants in tests/dev, not for input validation.

## 6. Logging standards

- Library: structlog; output JSON (prod/ci) or console (local) per `logging.format`.
- Levels: `DEBUG` diagnostic detail (off by default), `INFO` lifecycle events, `WARNING` degraded but continuing (fallbacks, retries), `ERROR` operation failed (run INVALID, API 500), `CRITICAL` process cannot continue.
- Every log line is an **event name** + key-values; no string interpolation of variables into the message.
- Mandatory context: `service`, `version`; bound when available: `campaign_id`, `run_id`, `worker_id`, `experiment_id`, `trace_id`.
- Never log secrets, tokens, full DSNs, or raw large arrays; log sizes/hashes instead. As a safety net, values of keys
  matching `token|password|secret|dsn|authorization` are masked by the redaction processor and tracebacks never
  include frame locals.
- Event catalogue (extend, don't rename; mirrored by `roboprobe.core.logging.EVENTS`, and a unit test fails on any
  logged event name missing from it):

| Event | Level | Keys |
|-------|-------|------|
| `campaign.state_changed` | INFO | from, to, reason |
| `campaign.tick` | DEBUG | inflight, enqueued |
| `strategy.proposed` | INFO | n, phases, propose_s |
| `selector.fallback` | WARNING | error_code |
| `run.claimed` / `run.started` / `run.finished` | INFO | backend, verdict, robustness, wall_s |
| `run.requeued` | WARNING | attempt, reason |
| `episode.launch_failed` | ERROR | stage, exit_code |
| `episode.teardown_orphans` | ERROR | pids |
| `analysis.finished` | INFO | n_runs, n_modes, wall_s |
| `analysis.skipped` | INFO | campaign_id, kind, reason |
| `artifact.path_rejected` | WARNING | artifact_id (no stored path or file contents) |
| `analysis.failed` | WARNING | campaign_id, kind, error |
| `analysis.artefact_write_failed` | WARNING | (exc_info) |
| `api.request` | INFO | method, route, status, duration_ms |
| `config.loaded` | INFO | sources (no values) |
| `scenario.unit_clipped` | WARNING | count, min, max |

## 7. Interface contracts

- Every port has: a Protocol/ABC with docstrings stating pre/post-conditions, a contract test suite (18 §4.3), and at least one fake implementation in `tests/fakes/`.
- Data crossing module boundaries uses immutable models from `roboprobe.core.types` (05 §1); no ORM objects, no DataFrames in public signatures (except analysis internals).
- Units in names or docstrings (`_s`, `_ms`, `_m`); arrays document shapes.

## 8. Concurrency rules

- Workers: one episode per slot; heartbeat in a separate thread; DB sessions never shared across threads.
- Orchestrator: per-campaign advisory lock; ticks are idempotent (re-running a tick never double-enqueues — enforced by unique `(campaign_id, ordinal, repeat_index)`).
- PyTorch threads limited by config; NumPy BLAS threads limited via `threadpoolctl` in workers to avoid oversubscription.

## 9. Performance conventions

Vectorise trace computations; avoid per-sample Python loops in oracles; cache GP fits per tick; keyset pagination in queries; stream large downloads.
