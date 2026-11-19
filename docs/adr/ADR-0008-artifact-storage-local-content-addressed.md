# ADR-0008: Content-addressed local artefact store behind an interface

| Field | Value |
|-------|-------|
| Status | Accepted |
| Date | 2026-11-19 |
| Deciders | Priyanshu Jha (owner) |
| Supersedes / Superseded by | – |

## Context
Traces, bags, logs, figures are large and binary; storing them in Postgres bloats it. Must be free and work offline.

## Decision
Store artefacts on the filesystem under `ARTIFACT_ROOT`, content-addressed by SHA-256 with browsable symlinks; metadata rows in `artifacts`. Access via `ArtifactStore` interface; an optional S3-compatible adapter (MinIO, self-hosted) may be added for remote workers.

## Alternatives considered
| Option | Assessment |
|--------|-----------|
| Postgres large objects | DB bloat, backups slow |
| MinIO by default | Extra service for single-laptop use |
| Cloud buckets | Not free long-term |

## Consequences
- + Deduplication, integrity check
- + Zero extra services
- − Remote workers need a sync mechanism (rsync/MinIO adapter)

## Verification / compliance
`roboprobe gc` and integrity check `roboprobe artifacts verify`.
