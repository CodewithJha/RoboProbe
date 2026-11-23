# 14 — Workflows & End-to-End Sequence Diagrams

> Related: [04 Architecture](04-system-architecture.md) · [10 §5 Gazebo episode](10-simulator-integration.md#5-episode-lifecycle-gazebo) · [09 §8 Analysis](09-failure-analysis-and-risk-mapping.md#8-sequence-automatic-post-campaign-analysis)

## 1. Overall user workflow

```mermaid
flowchart TD
    A["Write or pick scenario space YAML"] --> B["Validate and register space"]
    B --> C["Create campaign: backend, strategy, budget"]
    C --> D["Start campaign"]
    D --> E["Watch console: failures and cases appear"]
    E --> F{"Enough evidence?"}
    F -->|"no"| E
    F -->|"yes, or budget done"| G["Final analysis and risk atlas"]
    G --> H["Inspect cases, confirm interactions, replay"]
    H --> I["Export regression scenarios"]
    H --> J["Generate report"]
    I --> K["Developer fixes robot stack"]
    K --> L["Re-run regression and compare robustness"]
    L --> J
```

## 2. Campaign create → start → first proposals

```mermaid
sequenceDiagram
    actor U as User
    participant W as Dashboard
    participant A as API
    participant DB as PostgreSQL
    participant O as Orchestrator
    participant S as Strategy S-PROBE
    U->>W: complete wizard, click Start
    W->>A: POST /campaigns (start=true)
    A->>A: validate space, backend capabilities, strategy params
    A->>DB: INSERT campaign status RUNNING, INSERT event, NOTIFY
    A-->>W: 201 Campaign
    W->>A: GET /events?campaign_id (SSE)
    O->>DB: poll RUNNING campaigns, pg_try_advisory_lock(campaign)
    O->>DB: load history, strategy_state
    O->>S: propose(history, pending, q)
    S-->>O: proposals with phase and rationale
    O->>DB: INSERT runs PENDING with derived seeds, UPSERT strategy_state, NOTIFY
    A-->>W: event campaign.updated
```

## 3. Campaign state machine

```mermaid
stateDiagram-v2
    [*] --> CREATED
    CREATED --> RUNNING: start
    RUNNING --> PAUSED: pause, or auto-pause on infra alert
    PAUSED --> RUNNING: resume
    RUNNING --> ANALYZING: budget or finite strategy exhausted, or stop rule met
    ANALYZING --> COMPLETED: analysis done
    ANALYZING --> FAILED: analysis error after retries
    RUNNING --> FAILED: unrecoverable orchestrator error
    CREATED --> CANCELLED: cancel
    RUNNING --> CANCELLED: cancel
    PAUSED --> CANCELLED: cancel
    COMPLETED --> ANALYZING: manual re-analyze
    COMPLETED --> [*]
    FAILED --> [*]
    CANCELLED --> [*]
```

Stop rules (campaign `stop_rules`, all optional): `max_modes`, `max_wall_s`, `max_consecutive_invalid` (default 10 ⇒ auto-pause), `invalid_ratio` (> 0.2 after ≥ 20 runs ⇒ auto-pause).

Workers can claim explicitly queued Casebook confirmations, replays, and Atlas manual probes
after a campaign completes. The campaign stays completed, and strategy-generated runs are not restarted.
The final confirmation run commits the interaction verdict and publishes a campaign update
in the same transaction. Existing case labels, statuses and member assignments are preserved.

## 4. Worker executes a run

```mermaid
sequenceDiagram
    participant WK as Worker
    participant DB as PostgreSQL
    participant B as SimulatorBackend
    participant OR as VerdictEngine
    participant AS as ArtifactStore
    loop every poll_interval_s when idle
        WK->>DB: claim next PENDING run for my backend (SKIP LOCKED)
    end
    DB-->>WK: run row
    par heartbeat thread
        WK->>DB: UPDATE workers.last_heartbeat every heartbeat_interval_s
    and execution
        WK->>DB: status RUNNING, event run.started
        WK->>B: materialize(request)
        WK->>B: run_episode(request, materialized)
        B-->>WK: EpisodeResult (trace, artifacts, meta)
        WK->>DB: status EVALUATING
        WK->>OR: judge(result, task)
        OR-->>WK: RunOutcome (verdict, rho, classes)
        WK->>AS: put trace, manifest, log, world, bag
        WK->>DB: one transaction: run DONE + outcome + oracle_results + artifacts + event run.finished, NOTIFY
    end
```

## 5. Failure recovery (worker crash)

```mermaid
sequenceDiagram
    participant WK as Worker A
    participant DB as PostgreSQL
    participant RP as Reaper (orchestrator)
    participant WB as Worker B
    WK->>DB: claim run 57, RUNNING
    Note over WK: container killed (OOM or segfault)
    RP->>DB: every reaper_interval_s find runs whose worker heartbeat is older than heartbeat_timeout_s
    RP->>DB: run 57 to PENDING, attempt 1 (max_attempts 3)
    WB->>DB: claim run 57
    WB->>DB: run 57 DONE
    Note over RP,DB: if attempts exhausted then ERROR and verdict INVALID
```

## 6. Live updates to the browser

```mermaid
sequenceDiagram
    participant WK as Worker
    participant DB as PostgreSQL
    participant L as API event listener
    participant H as SSE hub
    participant B as Browser
    WK->>DB: INSERT events (run.finished), NOTIFY roboprobe_events id
    DB-->>L: notification with event id
    L->>DB: SELECT events WHERE id > last_seen
    L->>H: publish to campaign channel
    H-->>B: event run.finished (id = events.id)
    B->>B: TanStack Query cache patch, prepend entry tag
    Note over B,H: on reconnect the browser sends Last-Event-ID, hub replays missed events from table
```

## 7. Replay a failure (reproducibility)

```mermaid
sequenceDiagram
    actor D as Developer
    participant A as API
    participant DB as PostgreSQL
    participant WK as Worker
    D->>A: POST /runs/57:replay {repeats 5, fresh_seeds false}
    A->>DB: INSERT 5 runs (phase replay, replay_of 57, same scenario, same seed, priority 10)
    WK->>DB: claim and execute each
    WK->>DB: results
    A-->>D: GET /runs/57 shows replays 5 of 5 FAIL, rho list
    Note over D,A: kinematic2d must give identical traces, Gazebo reports agreement ratio
```

## 8. Strategy comparison experiment

```mermaid
flowchart TD
    E["experiment.yaml: strategies x seeds x budget, backend"] --> P["Plan: one campaign per strategy and seed"]
    P --> Q["Queue campaigns, max_concurrent_campaigns from config"]
    Q --> R["Each campaign runs normally, no auto confirm runs"]
    R --> M["Compute MET-01..08 per campaign"]
    M --> S["Statistics: Mann-Whitney U, A12, bootstrap CI, Holm"]
    S --> C["Comparison stored in experiments.results"]
    C --> V["Trials view and experiment report"]
```

Fairness rules: identical budget, backend, space, SUT profile and seed set for every strategy; the
`k`-th seed of every strategy uses the same derived seed stream for the simulator (common random
numbers) so differences come from the strategy, not luck.

## 9. Regression workflow in CI (developer's robot repo)

```mermaid
flowchart LR
    F["Exported failure scenarios<br/>regressions/*.yaml"] --> CI["CI job: roboprobe run --scenario each"]
    CI --> V{"verdict matches expect?"}
    V -->|"yes"| OK["pass"]
    V -->|"no"| X["fail build, attach trace and report"]
```

## 10. Developer workflow for building RoboProbe itself (AI agent loop)

```mermaid
flowchart TD
    T["Pick next READY task in 22"] --> R["Read linked docs and DoR checklist 32"]
    R --> B["Create branch feat/T-NNN-short-name"]
    B --> TDD["Write failing tests first"]
    TDD --> I["Implement to pass tests"]
    I --> L["ruff, mypy, import-linter, pytest locally"]
    L --> D["Update docs if behaviour changed, CHANGELOG entry"]
    D --> PR["Open PR with template, link task and requirement IDs"]
    PR --> CI["CI green"]
    CI --> REV["Review checklist 32"]
    REV --> M["Squash merge to main"]
    M --> T
```
