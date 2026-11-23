# syntax=docker/dockerfile:1.7
ARG UPSTREAM_IMAGE=otel/opentelemetry-collector@sha256:580cc87f5ea6c9e3969c37f3c5394b7a8385abb8189df0ddc63b9575a00f52fc
FROM busybox:1.37.0-musl@sha256:f6a95d611e0a8780fabdb2aec43e31275b2720dfefa3e41b16835bfc42454478 AS probe
# hadolint ignore=DL3006
FROM ${UPSTREAM_IMAGE}
COPY --from=probe --chmod=555 /bin/busybox /roboprobe-health/busybox
