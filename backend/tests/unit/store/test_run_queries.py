"""Filtering precedes bounded keyset reads (T-081d, FR-API-001)."""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from roboprobe.core.errors import ValidationError
from roboprobe.store import run_queries
from roboprobe.store.run_queries import query_runs

pytestmark = pytest.mark.unit


def test_filtered_query_is_bounded_and_has_stable_order() -> None:
    session = MagicMock()
    session.scalars.return_value.all.return_value = []
    query_runs(
        session,
        uuid4(),
        limit=10,
        cursor=None,
        sort="-robustness",
        status="DONE",
        verdict="FAIL",
        phase="manual",
        failure_class="F-COL",
        tags=("review",),
    )
    statement = session.scalars.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "runs.status =" in sql
    assert "runs.verdict =" in sql
    assert "runs.phase =" in sql
    assert "runs.primary_failure =" in sql
    assert "runs.tags @>" in sql
    assert "runs.id DESC" in sql
    assert statement._limit_clause.value == 11


@pytest.mark.parametrize("cursor", ["!", "e30=", "W10=", "null"])
def test_invalid_cursor_is_validation_error(cursor: str) -> None:
    with pytest.raises(ValidationError):
        query_runs(MagicMock(), uuid4(), limit=10, cursor=cursor)


@pytest.mark.parametrize(
    "sort", ["ordinal", "-ordinal", "finished_at", "-finished_at", "robustness", "-robustness"]
)
def test_cursor_roundtrip_retains_sort_and_tie_breaker(
    monkeypatch: pytest.MonkeyPatch, sort: str
) -> None:

    rows = [
        SimpleNamespace(id=uuid4(), ordinal=2, finished_at=None, robustness=None) for _ in range(2)
    ]
    monkeypatch.setattr(run_queries, "run_record", lambda row: row)
    session = MagicMock()
    session.scalars.return_value.all.return_value = rows
    first = query_runs(session, uuid4(), limit=1, cursor=None, sort=sort)
    assert first.next_cursor is not None
    session.scalars.return_value.all.return_value = rows[1:]
    second = query_runs(session, uuid4(), limit=1, cursor=first.next_cursor, sort=sort)
    assert second.items[0].id == rows[1].id
    assert second.next_cursor is None
    statement = session.scalars.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "runs.id) <" in sql if sort.startswith("-") else "runs.id) >" in sql
    other = "-ordinal" if sort == "ordinal" else "ordinal"
    with pytest.raises(ValidationError):
        query_runs(session, uuid4(), limit=1, cursor=first.next_cursor, sort=other)


@pytest.mark.parametrize(
    "sort,value,identifier",
    [
        ("ordinal", [], "id"),
        ("ordinal", True, "id"),
        ("ordinal", -1, "id"),
        ("ordinal", 2**100, "id"),
        ("robustness", {}, "id"),
        ("robustness", float("nan"), "id"),
        ("finished_at", 7, "id"),
        ("finished_at", "2026-01-01", "id"),
        ("ordinal", 1, 3),
    ],
)
def test_cursor_values_are_validated_before_sql(
    sort: str, value: object, identifier: object
) -> None:
    payload = {
        "sort": sort,
        "value": value,
        "id": str(uuid4()) if identifier == "id" else identifier,
    }
    cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    with pytest.raises(ValidationError):
        query_runs(MagicMock(), uuid4(), limit=10, cursor=cursor, sort=sort)
