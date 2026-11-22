# syntax=docker/dockerfile:1.11
# RoboProbe dashboard production image (T-116, docs/17 §5, NFR-DEP-001 / NFR-SEC-001).
# Build context: repository root (see docker/compose.yaml web.build).
#
#   docker build -f docker/web/Dockerfile \
#     --build-arg VERSION="$(git describe --tags --always)" --build-arg REVISION="$(git rev-parse HEAD)" \
#     -t roboprobe-web:dev .

ARG NODE_IMAGE=node:24-alpine@sha256:116b800c3754b440ee0aa3ed2f20f5bf3d99a554bfd9adeea09ea8017f6e85f5
ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:1.27-alpine@sha256:65e3e85dbaed8ba248841d9d58a899b6197106c23cb0ff1a132b7bfe0547e4c0

# hadolint ignore=DL3006
FROM ${NODE_IMAGE} AS build
WORKDIR /app/web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

# hadolint ignore=DL3006
FROM ${NGINX_IMAGE} AS runtime
USER root
RUN apk add --no-cache wget
COPY docker/web/nginx.conf /etc/nginx/nginx.conf
COPY docker/web/40-config-json.sh /docker-entrypoint.d/40-config-json.sh
RUN chmod +x /docker-entrypoint.d/40-config-json.sh
COPY --from=build /app/web/dist /usr/share/nginx/html
USER 101

ARG VERSION=dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="roboprobe-web" \
    org.opencontainers.image.version="${VERSION}" \
    org.opencontainers.image.revision="${REVISION}"

ENV NGINX_CONFIG_JSON_DIR=/var/lib/nginx/runtime
EXPOSE 8080