# 04 — System Architecture

> Style: C4 model (context → container → component) rendered as Mermaid flowcharts.
> Related: [34 Principles & patterns](34-design-principles-patterns-and-conventions.md) · [27 Configuration](27-configuration-reference.md) · [29 Deployment](29-deployment-guide.md) · [05 Module design](05-module-detailed-design.md) · [10 Simulator](10-simulator-integration.md) · [15 ADRs](15-tech-stack-and-adrs.md)

## 1. Architectural drivers

| Driver | Source | Architectural response |
|--------|--------|------------------------|
| Simulations are expensive (Gazebo ≈ 60–150 s each) | 01 §2 | Sample-efficient selector (GP-BO), batch proposals, parallel workers |
| Must develop/test without ROS or GPU | Constraint | `SimulatorBackend` port + `kinematic2d` adapter (hexagonal architecture) |
| Reproducibility of rare failures | G9 | Seed derivation tree, provenance manifest, pure-function oracles |
| Zero cost, single laptop | G10 | One PostgreSQL for data **and** job queue; Docker Compose; no message broker |
| Research comparability | G7 | Strategy plugin interface; experiments are first-class |
| Explainability | G5 | Analysis engine separated from selection; artefacts stored for re-analysis |
| Maintainability & modularity | PR-19, NFR-EXT-002 | Layered hexagonal core, import-linter contracts, one module per responsibility (M1–M8) |
| Extensibility | PR-19, NFR-EXT-001 | Ports + entry-point plugins for simulators, strategies, oracles, analyzers, stores ([ADR-0016](adr/ADR-0016-plugin-architecture-entry-points.md)) |
| Scalability | PR-16, NFR-SCAL-* | Stateless pull-based workers, batch proposals, horizontal scale across hosts without code change |
| Deployability | PR-13, NFR-DEP-* | Containers, env-based typed config, one-command up, automated migrations, CI-built images |
| No hard-coded values | PR-12, NFR-CFG-* | Typed layered settings injected at composition roots ([ADR-0015](adr/ADR-0015-typed-layered-configuration.md)) |

## 2. Architectural style

- **Hexagonal (ports & adapters)** in the core: domain logic (`scenario`, `selection`, `oracles`,
  `analysis`, `risk`) depends only on interfaces; adapters implement simulators, persistence and the API.
- **Orchestrator–worker** for execution: one orchestrator per campaign loop; N stateless workers pull jobs.
- **Database-as-queue** (PostgreSQL `SKIP LOCKED`) — [ADR-0007](adr/ADR-0007-postgresql-store-and-job-queue.md).
- **Event notification** via PostgreSQL `LISTEN/NOTIFY` → API → browser SSE — [ADR-0011](adr/ADR-0011-server-sent-events-for-live-updates.md).

### 2.1 Layers and ports at a glance

```mermaid
flowchart LR
    subgraph IF["Interface adapters"]
        REST["REST + SSE API"]
        CLIX["CLI"]
    end
    subgraph APP["Application services"]
        CL["CampaignLoop"]
        WP["WorkerProcess"]
        AJR["AnalysisJobRunner"]
        EXR["ExperimentRunner"]
    end
    subgraph DOM["Domain (pure)"]
        D1["scenario"]
        D2["selection"]
        D3["oracles"]
        D4["analysis + risk"]
        D5["metrics"]
    end
    subgraph PORTS["Ports (interfaces)"]
        P1["SimulatorBackend"]
        P2["RunQueue + Repositories + UnitOfWork"]
        P3["ArtifactStore"]
        P4["Strategy / Oracle / Analyzer plugin APIs"]
    end
    subgraph INFRA["Infrastructure adapters"]
        A1["kinematic2d, gazebo_nav2, replay"]
        A2["PostgreSQL (SQLAlchemy)"]
        A3["Local FS store, optional MinIO"]
    end
    IF --> APP
    APP --> DOM
    APP --> PORTS
    INFRA -.->|"implements"| PORTS
    DOM --> P4
```
Swapping any adapter (simulator, database/queue, artefact store) or adding a plugin touches only the
`INFRA` box and the composition root; domain and application code are unchanged.

## 3. C4 Level 1 — System context

```mermaid
flowchart TB
    TE(["Test engineer<br/>(browser / CLI)"])
    DEV(["Robot developer"])
    CI(["GitHub Actions CI"])
    RP["RoboProbe<br/>Adaptive testing and failure discovery platform"]
    GZ["Gazebo Harmonic<br/>physics + sensors"]
    ROS["ROS 2 Jazzy + Nav2<br/>robot stack under test"]
    GH["GitHub repository<br/>code, docs, releases"]
    TE -->|"defines spaces, runs campaigns, reads reports"| RP
    DEV -->|"replays failures, exports regressions"| RP
    CI -->|"runs kinematic2d campaigns as tests"| RP
    RP -->|"launches worlds, applies perturbations"| GZ
    RP -->|"sends goals, records topics"| ROS
    GZ <-->|"ros_gz bridge"| ROS
    RP -.->|"regression scenarios committed by developer"| GH
```

## 4. C4 Level 2 — Containers

```mermaid
flowchart LR
    subgraph Browser
        WEB["Dashboard SPA<br/>React 19 + TypeScript + Vite"]
    end
    subgraph Host["Docker Compose on one machine"]
        API["API service<br/>FastAPI + Uvicorn<br/>REST /api/v1 + SSE"]
        ORCH["Orchestrator service<br/>campaign loops, strategies M3,<br/>analysis M6, risk M7"]
        DB[("PostgreSQL 17<br/>entities + job queue<br/>LISTEN/NOTIFY")]
        ART[("Artifact store<br/>volume ./data/artifacts<br/>Parquet, MCAP, SVG, HTML")]
        WK1["Worker: kinematic2d<br/>pure Python, x N"]
        WK2["Worker: gazebo_nav2<br/>ROS 2 Jazzy + Gazebo Harmonic<br/>container, x N"]
    end
    WEB -->|"HTTP JSON, SSE"| API
    API --> DB
    API --> ART
    ORCH --> DB
    ORCH --> ART
    WK1 -->|"claim job, heartbeat, results"| DB
    WK2 -->|"claim job, heartbeat, results"| DB
    WK1 --> ART
    WK2 --> ART
```

| Container | Tech | Responsibility | Scales |
|-----------|------|----------------|--------|
| Dashboard | React, TanStack Query, Plotly.js | M8 UI | static files |
| API | FastAPI, Pydantic v2, SQLAlchemy 2 | CRUD, commands, SSE fan-out, report download | 1 |
| Orchestrator | Python, BoTorch, scikit-learn | campaign state machine, proposals, analysis jobs | 1 (leader lock) |
| Worker (kinematic2d) | Python, NumPy | executes runs in-process | 1…cores |
| Worker (gazebo_nav2) | Python + rclpy inside ROS image | launches Gazebo/Nav2 per run, records trace | 1…3 on a laptop |
| PostgreSQL | postgres:17 | system of record, queue, notifications | 1 |
| Artifact store | local filesystem volume | large binary/columnar artefacts | 1 |

The **CLI** (`roboprobe`) is the same Python package; `roboprobe campaign run --inline` runs the
orchestrator and N kinematic2d workers as threads/processes of one command against the same PostgreSQL
(useful for scripting and CI). Automated tests use a throw-away PostgreSQL from Testcontainers or the
CI service container — never SQLite, so SQL (e.g. `SKIP LOCKED`, `JSONB`) is identical everywhere.

## 5. C4 Level 3 — Components (orchestrator + core library)

```mermaid
flowchart TB
    subgraph Core["roboprobe core library"]
        SCN["M2 scenario<br/>ScenarioSpace, Sampler,<br/>Normalizer, Materializer"]
        SEL["M3 selection<br/>Strategy registry:<br/>RANDOM LHS SOBOL GRID OFAT BO LSE PROBE"]
        SUR["selection.surrogate<br/>GP model on robustness"]
        ORC["M5 oracles<br/>Oracle registry, VerdictEngine"]
        ANA["M6 analysis<br/>FeatureBuilder, HDBSCAN clusterer,<br/>SHAP explainer, RuleExtractor"]
        RSK["M7 risk<br/>RiskMapper, VolumeEstimator"]
        MET["metrics<br/>MET-01..08, statistics"]
        STO["store<br/>Repositories, UnitOfWork,<br/>ArtifactStore"]
        CORE["core<br/>types, config, seeding,<br/>logging, errors"]
    end
    subgraph Orchestrator
        LOOP["CampaignLoop<br/>state machine"]
        SCHED["Scheduler<br/>batch size, worker availability"]
        AJ["AnalysisJobRunner"]
    end
    subgraph Worker
        WRK["WorkerProcess<br/>claim, heartbeat, execute"]
        BK["M1 backends<br/>SimulatorBackend port"]
        K2D["kinematic2d adapter"]
        GZA["gazebo_nav2 adapter"]
        REC["TraceRecorder"]
    end
    LOOP --> SEL
    SEL --> SUR
    LOOP --> SCN
    LOOP --> SCHED
    SCHED --> STO
    AJ --> ANA
    AJ --> RSK
    RSK --> SUR
    WRK --> BK
    BK --> K2D
    BK --> GZA
    WRK --> REC
    WRK --> ORC
    WRK --> SCN
    WRK --> STO
    LOOP --> STO
    ANA --> STO
    MET --> STO
    SCN --> CORE
    SEL --> CORE
    ORC --> CORE
```

**Dependency rule:** arrows point *inwards*. `scenario`, `selection`, `oracles`, `analysis`, `risk`,
`metrics` MUST NOT import `store`, `api`, `backends`, `rclpy` or `fastapi`. They receive plain data
(`Scenario`, `Observation`, `Trace`) defined in `roboprobe.core.types`. Enforced by `import-linter`
contracts in CI (16 §6).

## 6. The intelligent loop (runtime view)

```mermaid
flowchart TD
    S0(["Campaign started"]) --> W["Warm-up proposals<br/>Sobol, n0 = max(2d, 10 percent of budget)"]
    W --> Q["Enqueue runs"]
    Q --> X["Workers execute on simulator"]
    X --> O["Oracles: verdict, class, robustness rho"]
    O --> U["Append Observation x, rho, verdict"]
    U --> B{"Budget left?"}
    B -->|"no"| FIN["Final analysis + risk map + report"]
    B -->|"yes"| FIT["Fit GP surrogate on rho"]
    FIT --> PH{"Phase controller"}
    PH -->|"falsify"| A1["Diversity-penalised LogEI<br/>find new failures"]
    PH -->|"boundary"| A2["Straddle / level-set<br/>refine pass-fail boundary"]
    PH -->|"refine"| A3["Local perturbation around<br/>new failure medoids"]
    A1 --> Q
    A2 --> Q
    A3 --> Q
    FIN --> E(["Campaign completed"])
```

## 7. Deployment view

```mermaid
flowchart TB
    subgraph Laptop["Developer laptop - Ubuntu 24.04 or WSL2"]
        subgraph Compose["docker compose project: roboprobe"]
            pg["postgres:17<br/>volume pgdata"]
            api["roboprobe-api<br/>:8000"]
            orch["roboprobe-orchestrator"]
            k2d["roboprobe-worker-k2d<br/>replicas: 4"]
            gzw["roboprobe-worker-gazebo<br/>profile: gazebo<br/>replicas: 1-3"]
            web["roboprobe-web nginx<br/>:8080"]
        end
        vol[("./data/artifacts<br/>bind mount")]
        br(["Browser"])
    end
    br --> web
    web -->|"/api proxy"| api
    api --> pg
    orch --> pg
    k2d --> pg
    gzw --> pg
    api --> vol
    orch --> vol
    k2d --> vol
    gzw --> vol
    subgraph Optional["Optional free-tier cloud VM"]
        rw["Remote gazebo workers<br/>connect to Postgres over WireGuard / SSH tunnel"]
    end
    rw -.-> pg
```

Ports: web 8080, API 8000 (bound to 127.0.0.1), Postgres 5432 (compose network only; exposed to host
only in `dev` profile). Remote workers are optional and need no code change: a worker is just a process
with a `DATABASE_URL` and an artefact sink (rsync/S3-compatible MinIO optional, ADR-0008).

## 8. Extension points (for future scope)

| Extension | Mechanism | Future feature |
|-----------|-----------|----------------|
| New simulator | implement `SimulatorBackend`, register entry point `roboprobe.backends` | Webots, MuJoCo, Isaac Sim |
| New strategy | implement `Strategy`, entry point `roboprobe.strategies` | CEM, AST (RL), adversarial generators |
| New oracle | implement `Oracle`, entry point `roboprobe.oracles` | Formal STL specs, VLA task success |
| New task | `TaskSpec` (start/goal/obstacle layout) in space YAML | multi-robot, manipulation |
| New analysis | `Analyzer` plugin | causal analysis, counterfactuals |
| Approval gate | campaign hook `before_enqueue` | human-in-the-loop high-risk approval |

## 9. Quality attribute scenarios

| QA | Stimulus | Response | Measure |
|----|----------|----------|---------|
| Availability | Gazebo worker segfaults mid-run | Heartbeat expires; run re-queued on another worker | No lost run; ≤ 35 s detection |
| Performance | 4 kinematic2d workers, budget 1 000 | Campaign completes | ≤ 15 min incl. GP fitting |
| Modifiability | Add Webots backend | Only new adapter package + config | 0 lines changed in core |
| Reproducibility | Replay failing kinematic2d run | Same trace | bit-identical |
| Usability | First-time user | Campaign started from wizard | ≤ 5 min |
| Testability | CI on every PR | Full loop with kinematic2d | ≤ 10 min pipeline |

## 10. Scalability path

| Stage | Throughput lever | Change required |
|-------|------------------|-----------------|
| S0 laptop, 1 Gazebo worker | sample-efficient selection | none |
| S1 laptop, N k2d / 2 Gazebo workers | `--scale`, `worker.concurrency`, `batch_size` | config only |
| S2 extra hosts (lab PCs, free-tier VM) | remote workers on same DB | config + network tunnel (29 §6) |
| S3 shared artefacts | `storage.backend=s3` (MinIO adapter) | new adapter (plugin), no core change |
| S4 cluster | same images on Kubernetes; Postgres managed/operator | deployment manifests only (future RFC) |
| S5 very large n | sparse/variational GP or local GPs in a new `Strategy` | new strategy plugin |
Queue semantics (SKIP LOCKED) and stateless workers make S1–S4 linear in worker count until the
database becomes the bottleneck (far beyond 100 workers at ~1 run/min each).

## 11. Cross-cutting concepts

- **Configuration:** typed `pydantic-settings` tree (27); precedence CLI flag > env var `ROBOPROBE_*` > `.env` > `roboprobe.toml` > defaults; validated at start-up; injected via composition roots — no module reads env vars or contains tunable literals.
- **Dependency injection:** constructor injection, one composition root per process (`roboprobe.bootstrap`, 34 §3).
- **Versioning:** API, schemas, oracle/strategy semantics and plugin API are versioned independently (33).
- **Seeding:** `numpy.random.SeedSequence(campaign_seed).spawn()` tree (21 §3).
- **Time:** all durations in seconds (float), timestamps `datetime` UTC aware.
- **Errors:** typed hierarchy `RoboProbeError` → `ConfigError`, `BackendError`, `OracleError`, `StoreError`; API maps to problem+json.
- **Logging:** `structlog` JSON with bound `campaign_id`, `run_id`, `worker_id`; event catalogue in 34 §6.
