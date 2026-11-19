# ADR-0009: FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic

| Field | Value |
|-------|-------|
| Status | Accepted |
| Date | 2026-11-19 |
| Deciders | Priyanshu Jha (owner) |
| Supersedes / Superseded by | – |

## Context

We need a typed Python API with auto-generated OpenAPI for a typed frontend client, SSE support, and robust migrations.

## Decision

FastAPI (+ Uvicorn) with Pydantic v2 DTOs, SQLAlchemy 2.0 ORM (typed `Mapped[]`), psycopg 3, Alembic migrations. Sync SQLAlchemy sessions in a threadpool for simplicity; async only for SSE.

## Alternatives considered

| Option | Assessment |
|--------|-----------|
| Django + DRF | Heavier, ORM less suited to analytical queries |
| Flask | No built-in validation/OpenAPI |
| Litestar | Smaller ecosystem |

## Consequences

- + OpenAPI → generated TS types
- + Same Pydantic models for config and DTOs
- − Need discipline to keep ORM out of DTOs

## Verification / compliance

OpenAPI snapshot diff in CI (oasdiff).
