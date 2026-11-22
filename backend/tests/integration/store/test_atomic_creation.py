"""Resource and replay response share a PostgreSQL transaction (T-081b)."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from tests.integration.store._seed import seed_campaign

from roboprobe.core.idempotency import IdempotencyRecord
from roboprobe.store.repositories.idempotency import SqlIdempotencyRepo
from roboprobe.store.uow import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.integration


def test_resource_and_cached_response_rollback_together(
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    cid = None
    with pytest.raises(RuntimeError), uow_factory() as uow:
        cid, _ = seed_campaign(uow)
        uow.idempotency.put(
            IdempotencyRecord(
                key=str(cid),
                method="POST",
                path="/campaigns",
                body_sha256="a" * 64,
                status=201,
                response_json={"id": str(cid)},
                created_at=datetime.now(UTC),
            )
        )
        raise RuntimeError
    with uow_factory() as uow:
        assert uow.campaigns.get(cid) is None
        assert uow.idempotency.get(str(cid)) is None


def test_idempotency_locks_release_with_the_resource_transaction(pg_engine: Engine) -> None:
    with Session(pg_engine) as first, Session(pg_engine) as second:
        one, two = SqlIdempotencyRepo(first), SqlIdempotencyRepo(second)
        assert one.try_lock("concurrent-test") is True
        assert two.try_lock("concurrent-test") is False
        first.rollback()
        assert two.try_lock("concurrent-test") is True
