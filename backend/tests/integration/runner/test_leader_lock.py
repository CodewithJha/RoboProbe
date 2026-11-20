"""Advisory lock: second orchestrator cannot acquire (T-041b)."""

from __future__ import annotations

import pytest

from roboprobe.store.ids import new_uuid
from roboprobe.store.locks import AdvisoryLock, campaign_lock_key

pytestmark = pytest.mark.integration


def test_second_orchestrator_cannot_acquire(pg_engine) -> None:
    key = campaign_lock_key(new_uuid())
    first = AdvisoryLock(pg_engine, key)
    second = AdvisoryLock(pg_engine, key)
    assert first.acquire() is True
    try:
        assert second.acquire() is False
    finally:
        first.release()
    assert second.acquire() is True
    second.release()
