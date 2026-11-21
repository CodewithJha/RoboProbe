"""HTTP compatibility exports for idempotency primitives (T-080d, T-081b)."""

from roboprobe.core.idempotency import (
    IdempotencyRecord,
    IdempotencyStore,
    body_sha256,
    purge_expired,
    remember,
    replay_or_begin,
)

__all__ = [
    "IdempotencyRecord",
    "IdempotencyStore",
    "body_sha256",
    "purge_expired",
    "remember",
    "replay_or_begin",
]
