# ADR-0013: Docker Compose deployment, GitHub Actions CI, GHCR images

| Field | Value |
|-------|-------|
| Status | Accepted |
| Date | 2026-11-19 |
| Deciders | Priyanshu Jha (owner) |
| Supersedes / Superseded by | – |

## Context

Must be deployable with one command on a laptop, reproducible, and use free CI.

## Decision

Docker Compose v2 with profiles (`core`, `gazebo`, `dev`, `observability`); images built in GitHub Actions and pushed to GHCR (free for public repos); `make up` / `docker compose --profile core up -d` as the one-command start. Horizontal scaling by `docker compose up --scale worker-k2d=N` and remote workers pointing at the same DB.

## Alternatives considered

| Option | Assessment |
|--------|-----------|
| Kubernetes | Overkill for one machine; future option via same images |
| Bare-metal scripts | Not reproducible |
| Paid CI | Not allowed |

## Consequences

- + One-command up, identical dev/prod
- + Free
- − Gazebo image is large (~3–4 GB)

## Verification / compliance

CI job builds all images; smoke test brings up `core` profile and runs a 10-run k2d campaign.
