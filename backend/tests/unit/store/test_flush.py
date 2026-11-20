"""Core SQL must flush pending ORM rows first."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from roboprobe.store.flush import execute

pytestmark = pytest.mark.unit


def test_execute_flushes_before_core_sql() -> None:
    session = MagicMock()
    session.execute.return_value = "ok"
    stmt = object()
    assert execute(session, stmt, {"k": 1}) == "ok"
    session.flush.assert_called_once_with()
    session.execute.assert_called_once_with(stmt, {"k": 1})
