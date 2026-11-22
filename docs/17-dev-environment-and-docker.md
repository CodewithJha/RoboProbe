# 17 — Development Environment & Docker

> Related: [29 Deployment guide](29-deployment-guide.md) · [27 Configuration](27-configuration-reference.md) · [ADR-0013](adr/ADR-0013-docker-compose-and-github-actions.md)

## 1. Supported developer setups

| Setup | Core + kinematic2d | Gazebo backend | Notes |
|-------|-------------------|----------------|-------|
| Ubuntu 24.04 native | ✅ | ✅ (Docker) | recommended |
| Windows 11 + WSL2 (Ubuntu 24.04) | ✅ | ✅ (Docker Desktop/WSL engine; WSLg for optional GUI) | allocate ≥ 8 GB RAM to WSL |
| macOS (Apple Silicon/Intel) | ✅ | ⚠️ (arm64 ROS images work but slow; use for core only) | |
| GitHub Codespaces (free monthly quota) | ✅ | ⚠️ (CPU only, slow) | optional |

Minimum hardware: 4 cores, 16 GB RAM, 25 GB free disk (Gazebo image ≈ 3–4 GB). No GPU required.

## 2. Prerequisites

`git`, Docker Engine ≥ 24 + Compose v2, `uv` (installs Python 3.12 automatically), Node.js 24 LTS + `pnpm` (via `corepack enable`), `make`.

## 3. First-time setup (one command each)

```bash
git clone https://github.com/CodewithJha/RoboProbe.git && cd RoboProbe
cp .env.example .env                       # edit only if you need non-defaults
make setup        # uv sync --all-extras (backend), pnpm install (web), pre-commit install
make up PROFILES=app  # postgres, api, orchestrator, worker-k2d x2, web
make demo         # registers warehouse_v1, runs a 50-run kinematic2d S-PROBE campaign
open http://localhost:8080
```

Native (no Docker) inner loop for core work:

```bash
make db-up PROFILES=dev                     # only postgres in Docker, published on 127.0.0.1:5432
export ROBOPROBE_DATABASE__PASSWORD_FILE=secrets/db_password
uv run roboprobe db upgrade
uv run roboprobe campaign run configs/campaigns/k2d_probe_smoke.yaml --inline --workers 4
uv run pytest -m "not sim"                   # fast tests
pnpm --dir web dev                           # Vite dev server on :5173, proxies /api to :8000
```

## 4. Compose services (`docker/compose.yaml`)

| Service | Image | Profile | Env (key ones) | Ports | Depends on |
|---------|-------|---------|----------------|-------|-----------|
| `postgres` | `postgres:17` (digest-pinned) | core, app, dev | `POSTGRES_PASSWORD_FILE` | 5432 (dev profile only) | – |
| `migrate` | `roboprobe-backend` | core, app | `ROBOPROBE_DATABASE__URL` | – | postgres healthy |
| `api` | `roboprobe-backend` | app | `api_token` Docker secret | internal 8000 | migrate done |
| `orchestrator` | `roboprobe-backend` | core, app | `ROBOPROBE_RUNNER__*` | – | migrate done |
| `worker-k2d` | `roboprobe-backend` | core, app | `ROBOPROBE_WORKER__BACKEND=kinematic2d` | – | migrate done |
| `worker-gazebo` | `roboprobe-gazebo` | gazebo | `ROBOPROBE_WORKER__BACKEND=gazebo_nav2`, `ROBOPROBE_BACKENDS__GAZEBO_NAV2__*` | – | migrate done |
| `web` | `roboprobe-web` (nginx) | app | runtime `config.json` | 127.0.0.1:8080 | api healthy |
| `prometheus`, `grafana` | official OSS images | observability | – | 9090, 3000 | api |

Volumes: `pgdata` (named), `./data/artifacts` (bind, shared by api/orchestrator/workers), `./data/workdirs` (bind, Gazebo scratch).
Health checks use `pg_isready` for Postgres, authenticated `GET /health/ready` for the API,
and internal `/healthz` for workers (heartbeat age). Compose stores temporary backend workdirs in `/tmp/roboprobe-workdirs`.
Make targets (T-005b): `make up` (builds the backend image unless `UP_FLAGS=` is given, starts `PROFILES`, default `core`, and fails if the
one-shot `migrate` job fails), `make down` (removes containers and network, keeps `pgdata`), `make db-up`, `make logs`, `make ps`.
Postgres is reachable from the host only with the `dev` profile (`PROFILES=dev` or `PROFILES="core dev"`): a loopback-bound TCP forwarder
(`postgres-port`) publishes `127.0.0.1:${ROBOPROBE_DB_PORT:-5432}`, because Compose cannot publish a port per profile.
`make setup` generates missing `secrets/db_password` and `secrets/api_token` files.
Open the dashboard's Settings page to enter the API token for the browser session.
On a native Linux Docker host, grant the backend container user (UID/GID 10001) write access to `data/artifacts` before starting the app profile.

Scaling: `docker compose up -d --scale worker-k2d=6` · Gazebo: `--profile gazebo up -d --scale worker-gazebo=2`.

### 4.1 Compose skeleton (illustrative; the real file is created in T-005)

```yaml
name: roboprobe
x-backend: &backend
  image: ghcr.io/codewithjha/roboprobe-backend:${ROBOPROBE_IMAGE_TAG:-dev}
  env_file: ../.env
  volumes: ["../data/artifacts:/data/artifacts"]
  restart: unless-stopped
services:
  postgres:
    image: postgres:17
    profiles: [core]
    environment:
      POSTGRES_DB: ${ROBOPROBE_DB_NAME:-roboprobe}
      POSTGRES_USER: ${ROBOPROBE_DB_USER:-roboprobe}
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets: [db_password]
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck: {test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER}"], interval: 5s, retries: 20}
  migrate:
    <<: *backend
    profiles: [core]
    command: ["db", "upgrade"]
    restart: "no"
    depends_on: {postgres: {condition: service_healthy}}
  api:
    <<: *backend
    profiles: [core]
    command: ["api"]
    ports: ["127.0.0.1:${ROBOPROBE_API_PORT:-8000}:8000"]
    depends_on: {migrate: {condition: service_completed_successfully}}
  orchestrator:
    <<: *backend
    profiles: [core]
    command: ["orchestrator"]
    depends_on: {migrate: {condition: service_completed_successfully}}
  worker-k2d:
    <<: *backend
    profiles: [core]
    command: ["worker", "--backend", "kinematic2d"]
    deploy: {replicas: ${ROBOPROBE_K2D_REPLICAS:-2}}
    depends_on: {migrate: {condition: service_completed_successfully}}
  worker-gazebo:
    image: ghcr.io/codewithjha/roboprobe-gazebo:${ROBOPROBE_IMAGE_TAG:-dev}
    profiles: [gazebo]
    env_file: ../.env
    command: ["roboprobe", "worker", "--backend", "gazebo_nav2"]
    shm_size: "1gb"
    volumes: ["../data/artifacts:/data/artifacts", "../data/workdirs:/work"]
    depends_on: {migrate: {condition: service_completed_successfully}}
  web:
    image: ghcr.io/codewithjha/roboprobe-web:${ROBOPROBE_IMAGE_TAG:-dev}
    profiles: [core]
    ports: ["127.0.0.1:${ROBOPROBE_WEB_PORT:-8080}:8080"]
    depends_on: [api]
secrets:
  db_password: {file: ../secrets/db_password}
volumes: {pgdata: {}}
```

## 5. Images

| Image | Base | Contents | Size target |
|-------|------|----------|-------------|
| `roboprobe-backend` | `python:3.12-slim` (multi-stage, uv) | `roboprobe[ml,api,worker]`, CPU torch wheel from the PyTorch CPU index | ≤ 1.5 GB |
| `roboprobe-gazebo` | `ros:jazzy-ros-base` (Ubuntu 24.04) | apt: `ros-jazzy-navigation2 ros-jazzy-nav2-bringup ros-jazzy-nav2-minimal-tb4-sim ros-jazzy-ros-gz ros-jazzy-rmw-cyclonedds-cpp ros-jazzy-rosbag2-storage-mcap`, Mesa EGL; venv `--system-site-packages` with `roboprobe[worker]` (no torch); colcon-built `roboprobe_ros` | ≤ 4 GB |
| `roboprobe-web` | `node:24` build → `nginxinc/nginx-unprivileged` | static SPA, `config.json` templated from env at start | ≤ 60 MB |

All images run as non-root, read-only root FS where possible, with OCI labels (`org.opencontainers.image.revision` = git SHA) used by provenance.

`roboprobe-backend` (`docker/backend.Dockerfile`, T-005a) has `ENTRYPOINT ["roboprobe"]`, so compose `command:` lists only the
subcommand. It runs as `roboprobe` (uid/gid 10001) with code under `/app` (read-only for that user) and `/data/artifacts` as
the only writable volume (`/app/data` links to `/data`, so the default `storage.artifact_root` lands there without any
env override); it works with `read_only: true` plus a `/tmp` tmpfs. A bind-mounted host directory must be writable by uid
10001 (`sudo chown 10001:10001 data/artifacts`); named volumes inherit the right owner from the image.
Build locally with
`docker build -f docker/backend.Dockerfile --build-arg VERSION=$(git describe --tags --always) --build-arg REVISION=$(git rev-parse HEAD) -t roboprobe-backend:dev .`;
`.dockerignore` allow-lists the build context, so `.env`, `secrets/` and `data/` never reach a layer.

## 6. Running Gazebo visually (debugging)

`make gz-debug RUN=<run_id>` re-materialises a run and launches Gazebo GUI + RViz in the container with X11/WSLg forwarding (`DISPLAY`, `/tmp/.X11-unix`). Not used in automated runs.

## 7. Useful make targets

`setup, up, down, logs, ps, db-up, db-shell, migrate, test, test-fast, test-sim, lint, typecheck, fmt, web-dev, docs-check (markdownlint + mermaid + links), config-docs, demo, gz-build, gz-debug, clean`.

## 8. Troubleshooting (dev)

| Symptom | Fix |
|---------|-----|
| `worker-gazebo` RTF < 0.5 | lower `ROBOPROBE_BACKENDS__GAZEBO_NAV2__MAX_PARALLEL_PER_HOST` to 1; close browsers; check `LIBGL_ALWAYS_SOFTWARE` |
| Nav2 never becomes active | inspect `episode.log` artefact; increase `startup_timeout_s`; verify `topics.yaml` |
| DDS discovery across workers | ensure unique `ROS_DOMAIN_ID` per slot and `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` |
| WSL2 out of memory | `.wslconfig` `memory=10GB`, `swap=8GB` |
| Dashboard port already used | change `ROBOPROBE_WEB_PORT` in `.env` |

More in [30 Operations runbook](30-operations-runbook.md).
