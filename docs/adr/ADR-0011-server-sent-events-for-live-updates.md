# ADR-0011: Server-Sent Events for live updates

| Field | Value |
|-------|-------|
| Status | Accepted |
| Date | 2026-11-19 |
| Deciders | Priyanshu Jha (owner) |
| Supersedes / Superseded by | – |

## Context

The dashboard needs server→client push of run/campaign events; commands go through REST.

## Decision

Use SSE (`sse-starlette`) fed from the Postgres outbox (`events` table + NOTIFY), with `Last-Event-ID` resume.

## Alternatives considered

| Option | Assessment |
|--------|-----------|
| WebSockets | Bidirectional not needed; more complex proxies/reconnect |
| Polling | Wasteful, laggy |

## Consequences

- + Simple, HTTP-native, auto-reconnect in browsers
- − One-way only (fine)

## Verification / compliance

FR-DSH-002 latency test ≤ 2 s.
