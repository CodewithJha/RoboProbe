# 15 — Technology Stack & ADR Summary

> Every item is free and open-source (NFR-COST-001). Versions: **pin exact versions in lockfiles**
> (`uv.lock`, `pnpm-lock.yaml`, Docker image digests); the minimums below are what the design assumes.
> Upgrades follow [33 Versioning policy](33-versioning-release-and-changelog-policy.md).

## 1. Stack by layer

| Layer | Choice | Min version | Licence | Why (ADR) |
|-------|--------|-------------|---------|-----------|
| Language (core) | Python | 3.12 | PSF | ROS 2 Jazzy's system Python on Ubuntu 24.04 is 3.12; BoTorch/Ax require ≥ 3.11 ([ADR-0004](adr/ADR-0004-python-312-uv-monorepo.md)) |
| Package/env manager | uv | 0.5+ | MIT/Apache | fast, lockfile, workspaces (ADR-0004) |
| Numerics | NumPy, SciPy (`stats.qmc`) | 2.x, 1.14+ | BSD | arrays, LHS/Sobol, statistics |
| ML / BO | PyTorch (CPU), GPyTorch, BoTorch | 2.4+, 1.15+, 0.18+ | BSD/MIT | GP surrogate, LogEI, optimize_acqf ([ADR-0005](adr/ADR-0005-selection-gp-bayesian-optimisation-botorch.md)) |
| Classic ML | scikit-learn (HDBSCAN, HistGB, DecisionTree) | 1.5+ | BSD | clustering, classifiers ([ADR-0012](adr/ADR-0012-failure-analysis-hdbscan-shap-rules.md)) |
| Explainability | SHAP | 0.46+ | MIT | TreeExplainer + interaction values |
| Data | pandas, PyArrow (Parquet) | 2.2+, 17+ | BSD/Apache | traces, analysis tables |
| Config | pydantic v2, pydantic-settings, PyYAML, jsonschema | 2.8+ | MIT | typed validated settings ([27](27-configuration-reference.md)) |
| Templating | Jinja2, lxml | 3.1+, 5+ | BSD | reports, SDF patching |
| API | FastAPI, Uvicorn, sse-starlette | 0.115+, 0.30+ | MIT/BSD | REST + SSE ([ADR-0009](adr/ADR-0009-backend-fastapi-pydantic-sqlalchemy.md), [ADR-0011](adr/ADR-0011-server-sent-events-for-live-updates.md)) |
| ORM / migrations | SQLAlchemy 2, Alembic, psycopg 3 | 2.0+, 1.13+, 3.2+ | MIT/LGPL | DB access |
| Database | PostgreSQL | 17 | PostgreSQL | store + queue + notify ([ADR-0007](adr/ADR-0007-postgresql-store-and-job-queue.md)) |
| CLI | Typer, Rich | 0.12+ | MIT | `roboprobe` command |
| Logging / metrics | structlog, prometheus-client, OpenTelemetry SDK (optional) | 24+ | MIT/Apache | 21 |
| Plots (static report) | Matplotlib | 3.9+ | PSF-style | SVG figures |
| Robotics middleware | ROS 2 Jazzy (rclpy, ros2 launch, rosbag2 MCAP) | Jazzy | Apache 2.0 | ([ADR-0002](adr/ADR-0002-primary-simulator-gazebo-harmonic-ros2-jazzy.md)) |
| Simulator | Gazebo Harmonic + ros_gz | Harmonic | Apache 2.0 | ADR-0002 |
| Robot stack under test | Nav2 + nav2_minimal_tb4_sim (TurtleBot 4) | 1.3.x | Apache 2.0 | ADR-0002 |
| Dev backend | `kinematic2d` (own) | – | MIT | ([ADR-0003](adr/ADR-0003-kinematic2d-fallback-backend.md)) |
| Frontend | React, TypeScript, Vite | 19, 5.6+, 6+ | MIT | ([ADR-0010](adr/ADR-0010-frontend-react-typescript-vite.md)) |
| FE data/state | TanStack Query, TanStack Virtual, React Router | 5+, 3+, 7+ | MIT | |
| FE UI primitives | Radix UI, CSS Modules, @fontsource/ibm-plex-* | – | MIT / OFL | accessibility, original design |
| FE charts | Plotly.js (partial bundle) + custom SVG | 2.35+ | MIT | heatmaps, box plots |
| FE API types | openapi-typescript | 7+ | MIT | generated types |
| Node runtime / PM | Node.js 24 LTS, pnpm 9 | – | MIT | |
| Containers | Docker Engine + Compose v2 | 24+ | Apache 2.0 | ([ADR-0013](adr/ADR-0013-docker-compose-and-github-actions.md)) |
| CI/CD | GitHub Actions (free for public repos), GHCR | – | – | ADR-0013 |
| Python QA | pytest, pytest-cov, Hypothesis, pytest-benchmark, Testcontainers, ruff, mypy, import-linter, pip-audit | – | MIT/BSD/Apache | 18 |
| Web QA | Vitest, Testing Library, MSW, Playwright, axe-core, ESLint, Prettier | – | MIT/MPL | 18 |
| Docs | Markdown + Mermaid (GitHub-rendered), mermaid-cli for validation, markdownlint, lychee (links) | – | MIT | 20 |

Rejected/deferred: Celery/Redis/RabbitMQ (extra services; DB queue suffices — ADR-0007), Kubernetes
(overkill — ADR-0013), MongoDB (relational queries needed), Ax (less control over custom acquisitions;
may wrap later — ADR-0005), Isaac Sim (needs RTX GPU), Webots/MuJoCo as primary (less native Nav2/ROS 2
warehouse tooling — ADR-0002), Stable-Baselines3 RL as primary selector (sample-inefficient for static
parameters — ADR-0005), WebSockets (bidirectional not needed — ADR-0011), paid services of any kind.

## 2. ADR index

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-0001](adr/ADR-0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [ADR-0002](adr/ADR-0002-primary-simulator-gazebo-harmonic-ros2-jazzy.md) | Primary simulator: Gazebo Harmonic + ROS 2 Jazzy + Nav2 (TurtleBot 4, warehouse) | Accepted |
| [ADR-0003](adr/ADR-0003-kinematic2d-fallback-backend.md) | Lightweight `kinematic2d` backend for development, CI and ground truth | Accepted |
| [ADR-0004](adr/ADR-0004-python-312-uv-monorepo.md) | Python 3.12, uv, single monorepo | Accepted |
| [ADR-0005](adr/ADR-0005-selection-gp-bayesian-optimisation-botorch.md) | Intelligent selection: GP Bayesian optimisation + level-set active learning (BoTorch); RL deferred | Accepted |
| [ADR-0006](adr/ADR-0006-robustness-valued-oracles.md) | Continuous robustness-valued (STL-style) oracles | Accepted |
| [ADR-0007](adr/ADR-0007-postgresql-store-and-job-queue.md) | PostgreSQL as single store and job queue (SKIP LOCKED, LISTEN/NOTIFY) | Accepted |
| [ADR-0008](adr/ADR-0008-artifact-storage-local-content-addressed.md) | Content-addressed local artefact store behind an interface | Accepted |
| [ADR-0009](adr/ADR-0009-backend-fastapi-pydantic-sqlalchemy.md) | FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic | Accepted |
| [ADR-0010](adr/ADR-0010-frontend-react-typescript-vite.md) | React + TypeScript + Vite SPA with original "Field Notebook" design system | Accepted |
| [ADR-0011](adr/ADR-0011-server-sent-events-for-live-updates.md) | Server-Sent Events for live updates | Accepted |
| [ADR-0012](adr/ADR-0012-failure-analysis-hdbscan-shap-rules.md) | Failure analysis: HDBSCAN + SHAP + decision-tree rules | Accepted |
| [ADR-0013](adr/ADR-0013-docker-compose-and-github-actions.md) | Docker Compose deployment, GitHub Actions CI, GHCR images | Accepted |
| [ADR-0014](adr/ADR-0014-seeding-and-provenance.md) | Hierarchical seeding and per-run provenance manifests | Accepted |
| [ADR-0015](adr/ADR-0015-typed-layered-configuration.md) | Typed, layered configuration; no hard-coded values | Accepted |
| [ADR-0016](adr/ADR-0016-plugin-architecture-entry-points.md) | Plugin architecture via Python entry points + dependency injection at a composition root | Accepted |

New decisions use [templates/adr-template.md](templates/adr-template.md); larger proposals start as an RFC ([templates/rfc-template.md](templates/rfc-template.md)).
