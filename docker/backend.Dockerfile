# syntax=docker/dockerfile:1.7
# RoboProbe backend image (T-005a, docs/17 §5): one image for the `migrate`, `api`, `orchestrator` and
# `worker-k2d` compose services. Configured only through ROBOPROBE_* env vars and secret files
# (NFR-DEP-002, docs/27); nothing secret is baked in (NFR-SEC-002).
#
#   docker build -f docker/backend.Dockerfile \
#     --build-arg VERSION="$(git describe --tags --always)" --build-arg REVISION="$(git rev-parse HEAD)" \
#     -t roboprobe-backend:dev .
#   docker run --rm roboprobe-backend:dev --version
#
# Base images are pinned by tag *and* digest; bump both together (Renovate/Dependabot friendly).
ARG PYTHON_IMAGE=python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d

# Tags + digests live in the ARGs above (hadolint cannot see through ARG-based FROM lines).
# hadolint ignore=DL3006
FROM ${UV_IMAGE} AS uv

# --- builder: resolve the locked environment into /app/.venv -------------------------------------
# hadolint ignore=DL3006
FROM ${PYTHON_IMAGE} AS builder
COPY --from=uv /uv /usr/local/bin/uv

# Extras baked into the image (docs/17 §5): API server, k2d worker, ML selection/analysis.
ARG UV_EXTRAS="--extra api --extra worker --extra ml"
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /src/backend
# Dependencies first (cached layer while only source code changes); CPU-only torch comes from the
# pytorch-cpu index pinned in uv.lock.
COPY backend/pyproject.toml backend/uv.lock ./
# `--extra ml` pulls editable workspace plugins; sync must see them before lock resolution.
COPY plugins /src/plugins
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project ${UV_EXTRAS}

# The wheel force-includes ../schemas (pyproject [tool.hatch...force-include]).
COPY schemas /src/schemas
COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable ${UV_EXTRAS}

# Packages whose bundled `tests` packages are never imported at runtime. Not a blanket rule: some
# libraries (e.g. pyre_extensions, used by botorch) import their own `tests` module.
ARG PRUNE_TESTS_IN="numpy pandas scipy sklearn pyarrow matplotlib sympy"
# Drop build/test-only payload (C++ headers, bundled test suites and test binaries, ~0.3 GB) to stay
# within the docs/17 §5 size target. torch_shm_manager is kept: torch.multiprocessing needs it.
RUN site="$(/app/.venv/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')" \
 && rm -rf "${site}/torch/include" "${site}/torch/test" "${site}/pyarrow/include" \
 && find "${site}/torch/bin" -mindepth 1 ! -name torch_shm_manager -exec rm -rf {} + \
 && for pkg in ${PRUNE_TESTS_IN}; do find "${site}/${pkg}" -depth -type d -name tests -exec rm -rf {} +; done

# --- runtime: slim interpreter + venv, no build tooling --------------------------------------------
# hadolint ignore=DL3006
FROM ${PYTHON_IMAGE} AS runtime

ARG VERSION=dev
ARG REVISION=unknown
ARG SOURCE=https://github.com/CodewithJha/RoboProbe
ARG APP_UID=10001
ARG APP_GID=10001
LABEL org.opencontainers.image.title="roboprobe-backend" \
      org.opencontainers.image.description="RoboProbe API, orchestrator, migrations and kinematic2d worker" \
      org.opencontainers.image.source="${SOURCE}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="MIT"

RUN groupadd --system --gid "${APP_GID}" roboprobe \
 && useradd --system --uid "${APP_UID}" --gid roboprobe --home-dir /app --no-create-home \
      --shell /usr/sbin/nologin roboprobe \
 && install -d -o roboprobe -g roboprobe /data/artifacts \
 && install -d /app \
 && ln -s /data /app/data
RUN apt-get update \
 && apt-get -y --no-install-recommends upgrade \
 && rm -rf /var/lib/apt/lists/*

# Code and data are root-owned and read-only for the runtime user; only /data/artifacts is writable.
COPY --from=builder /app/.venv /app/.venv
COPY configs /app/configs
COPY tasks /app/tasks
COPY backend/alembic.ini /app/backend/alembic.ini
COPY backend/alembic /app/backend/alembic

ENV PATH=/app/.venv/bin:${PATH} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib

# Relative defaults resolve against /app (docs/27 §4.2, §4.5): configs/... is baked in and
# data/artifacts reaches the volume through the /app/data -> /data symlink. No ROBOPROBE_* env is
# set here, so .env / TOML / secret layers keep their normal precedence.
WORKDIR /app
VOLUME ["/data/artifacts"]
USER ${APP_UID}:${APP_GID}

# Compose picks the subcommand (`db upgrade`, `api`, `orchestrator`, `worker ...`); health checks are
# defined per service in compose, not here.
ENTRYPOINT ["roboprobe"]
