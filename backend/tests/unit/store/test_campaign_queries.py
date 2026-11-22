"""Campaign filter/keyset queries and atomic response storage (T-081b)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from roboprobe.core.errors import ValidationError
from roboprobe.core.idempotency import IdempotencyRecord
from roboprobe.store import campaign_queries
from roboprobe.store.repositories.idempotency import SqlIdempotencyRepo
from roboprobe.store.repositories.modes import SqlFailureModeRepo
from roboprobe.store.repositories.runs import SqlRunRepo

pytestmark = pytest.mark.unit


def test_campaign_query_filters_before_limit_and_uses_creation_ties(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        SimpleNamespace(id=uuid4(), created_at=datetime(2026, 1, 1, tzinfo=UTC)) for _ in range(2)
    ]
    session = MagicMock()
    session.scalars.return_value.all.return_value = records
    monkeypatch.setattr(campaign_queries, "campaign_record", lambda row: row)
    first = campaign_queries.query_campaigns(
        session, limit=1, status="RUNNING", strategy="S-PROBE", backend="kinematic2d"
    )
    sql = str(session.scalars.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "campaigns.status =" in sql and "campaigns.strategy_id =" in sql
    assert "campaigns.backend =" in sql and "campaigns.id DESC" in sql
    assert session.scalars.call_args.args[0]._limit_clause.value == 2
    assert first.next_cursor
    session.scalars.return_value.all.return_value = records[1:]
    second = campaign_queries.query_campaigns(session, limit=1, cursor=first.next_cursor)
    assert second.next_cursor is None
    sql = str(session.scalars.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "campaigns.id) <" in sql


@pytest.mark.parametrize("cursor", ["!", "e30=", "W10=", "null"])
def test_bad_campaign_cursor_is_validation_error(cursor: str) -> None:
    with pytest.raises(ValidationError):
        campaign_queries.query_campaigns(MagicMock(), limit=10, cursor=cursor)


def test_idempotency_repository_never_commits_independently() -> None:
    session = MagicMock()
    repo = SqlIdempotencyRepo(session)
    repo.put(
        IdempotencyRecord(
            key="key",
            method="POST",
            path="/campaigns",
            body_sha256="a" * 64,
            status=201,
            response_json={"id": "campaign"},
            created_at=datetime.now(UTC),
        )
    )
    session.merge.assert_called_once()
    session.flush.assert_called_once()
    session.commit.assert_not_called()
    session.execute.return_value.scalar_one.return_value = True
    assert repo.try_lock("key") is True
    sql = str(session.execute.call_args.args[0])
    assert "pg_try_advisory_xact_lock" in sql


def test_campaign_statistics_are_grouped_in_one_query() -> None:
    cid = uuid4()
    session = MagicMock()
    session.execute.return_value = [(cid, "PENDING", None, 9000, 1), (cid, "DONE", "FAIL", 1000, 2)]
    stats = SqlRunRepo(session).counts_for_campaigns([cid])
    assert stats[cid] == {"pending": 9000, "done": 1000, "fail": 1000, "first_failure_at": 2}
    session.execute.assert_called_once()
    assert SqlRunRepo(session).counts_for_campaigns([]) == {}
    session.execute.return_value = MagicMock()
    session.execute.return_value.all.return_value = [(cid, 3)]
    assert SqlFailureModeRepo(session).counts_for_campaigns([cid]) == {cid: 3}
