# ADR-0007: PostgreSQL as single store and job queue

| Field | Value |
|-------|-------|
| Status | Accepted |
| Date | 2026-11-19 |
| Deciders | Priyanshu Jha (owner) |
| Supersedes / Superseded by | – |

## Context
We need persistent entities, a reliable work queue for parallel workers, and change notifications — on a laptop, free, with minimal operational burden.

## Decision
Use **PostgreSQL 17** for all relational data, the run queue (`SELECT … FOR UPDATE SKIP LOCKED`), leader locks (advisory locks) and notifications (`LISTEN/NOTIFY` + transactional outbox table). No Redis/RabbitMQ/Celery. Queue access is behind a `RunQueue` interface so a broker can replace it if scale demands.

## Alternatives considered
| Option | Assessment |
|--------|-----------|
| Redis + Celery/RQ | Extra service; at-most/at-least-once nuances; no transactional coupling with run rows |
| RabbitMQ | Overkill |
| SQLite | No SKIP LOCKED, poor concurrency |
| MongoDB | Weak relational queries for analysis |

## Consequences
- + One service to run and back up
- + Exactly-once claim semantics within a transaction
- + Scales to dozens of workers, far beyond our needs
- − Polling interval adds ≤ 1 s latency (acceptable)

## Verification / compliance
Integration test FR-RUN-001 with 4 workers / 100 runs; chaos test NFR-REL-001.
