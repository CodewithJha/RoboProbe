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

The Compose demo requires Git, Docker Engine ≥ 24 with Compose v2, Make, and Python 3.
Running source checks on the host also requires `uv` (installs Python 3.12), Node.js 24,
and pnpm (via `corepack enable`).

## 3. First-time setup

Follow the [dashboard quickstart](../README.md#try-the-dashboard-locally) to build the stack
and run the 50-run warehouse demo. From the repository root, run `make setup` to install
the locked backend and web dependencies and Git hooks for host development.

For core development, run PostgreSQL in Compose and use the CLI on the host:

```bash
make db-up PROFILES=dev                     # Postgres on 127.0.0.1:5432
export ROBOPROBE_DATABASE__PASSWORD_FILE="$PWD/secrets/db_password"
uv run --project backend roboprobe db upgrade
uv run --project backend roboprobe campaign run configs/campaigns/k2d_probe_smoke.yaml --inline --workers 4
make test-fast
```

For dashboard development, run `(cd web && pnpm dev)` to start Vite on port 5173.
The dev server proxies `/api` to the local API on port 8000 by default.

## 4. Compose services

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

Volumes: `pgdata` (named) and `./data/artifacts` (bind, shared by API, orchestrator and workers).
Health checks use `pg_isready` for Postgres, authenticated `GET /health/ready` for the API,
and internal `/healthz` for workers (heartbeat age). Compose stores temporary backend workdirs in `/tmp/roboprobe-workdirs`.
For a worker started directly on the host, pass `roboprobe worker --backend kinematic2d --health`
to expose its probe. Set `ROBOPROBE_WORKER__HEALTH_PORT` for that process if an orchestrator or
another worker already uses the default port.
Make targets (T-005b): `make up` (builds images by default, starts `PROFILES`, default `core`, and fails if the
one-shot `migrate` job fails), `make down` (removes containers and network, keeps `pgdata`), `make db-up`, `make logs`, `make ps`.
Postgres is reachable from the host only with the `dev` profile (`PROFILES=dev` or `PROFILES="core dev"`): a loopback-bound TCP forwarder
(`postgres-port`) publishes `127.0.0.1:${ROBOPROBE_DB_PORT:-5432}`, because Compose cannot publish a port per profile.
`make setup` generates missing `secrets/db_password` and `secrets/api_token` files.
Open the dashboard's Settings page to enter the API token for the browser session.
On a native Linux Docker host, grant the backend container user (UID/GID 10001) write access to `data/artifacts` before starting the app profile.

Scale kinematic workers with `docker compose -f docker/compose.yaml --profile app up -d --scale worker-k2d=6`.
After [populating the Fuel cache](#5-images), start the Gazebo worker with
`make up PROFILES="core gazebo"`. Compose gives it an init process, a read-only root
filesystem, and the same artifact and database access as the kinematic worker. Its temporary
workdirs stay under `/tmp`, and the Fuel models persist in the `gazebo-fuel` volume.

### 4.1 Inspect the Compose model

The [checked-in Compose file](../docker/compose.yaml) defines the services, profile membership,
health checks, and dependencies. To list the services enabled by the app profile:

```bash
docker compose -f docker/compose.yaml --profile app config --services
```

## 5. Images

| Image | Base | Contents | Size target |
|-------|------|----------|-------------|
| `roboprobe-backend` | `python:3.12-slim` (multi-stage, uv) | `roboprobe[ml,api,worker]`, CPU torch wheel from the PyTorch CPU index | ≤ 1.5 GB |
| `roboprobe-gazebo` | `ros:jazzy-ros-base-noble` (Ubuntu 24.04) | Pinned Nav2, Harmonic, TB4, Cyclone DDS, and MCAP, plus Mesa EGL, the installed ROS workspace, and a separate locked Python venv | ≤ 4 GB |
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

The Gazebo image reads its architecture-specific ROS versions from `docker/gazebo/apt-pins.txt`.
For warehouse runs permitted by the upstream model licenses, populate the persistent cache
with the pinned versions from `docker/gazebo/fuel-models.txt` before starting the worker:

```bash
docker compose -f docker/compose.yaml --profile core --profile gazebo build worker-gazebo
docker compose -f docker/compose.yaml --profile core --profile gazebo run \
  --rm --no-deps worker-gazebo prefetch-fuel
```

The stock Warehouse v5 model uses the Creative Commons BY-NC-ND 4.0 license. The image
ships the version list and download helper. The pinned models stay in the local Fuel volume.
The worker records the apt versions, ROS distribution, Gazebo and Nav2 versions in each Gazebo
run manifest. Set `backends.gazebo_nav2.software_rendering` to force Mesa software rendering on
a host without usable GPU access.

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
