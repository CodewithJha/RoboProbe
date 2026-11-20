"""Self-tests for the PostgreSQL fixtures in ``tests/integration/conftest.py``."""

from __future__ import annotations

import pytest
from sqlalchemy import Connection, Engine, text

pytestmark = pytest.mark.integration

POSTGRES_MAJOR = 17


def test_server_is_postgres_17(pg_connection: Connection) -> None:
    version = pg_connection.execute(text("SHOW server_version_num")).scalar_one()
    major = int(version) // 10_000
    if major != POSTGRES_MAJOR:
        pytest.skip(f"expected PostgreSQL {POSTGRES_MAJOR} (CI image), got {major}")
    banner = pg_connection.execute(text("SELECT version()")).scalar_one()
    assert banner.startswith(f"PostgreSQL {POSTGRES_MAJOR}.")


def test_pg_connection_changes_are_never_committed(
    pg_connection: Connection, pg_engine: Engine
) -> None:
    table = "rp_fixture_isolation_probe"
    pg_connection.execute(text(f"CREATE TABLE {table} (id int)"))
    with pg_engine.connect() as other:
        visible = other.execute(text("SELECT to_regclass(:name)"), {"name": table}).scalar()
    assert visible is None


def test_pg_connection_is_inside_a_transaction(pg_connection: Connection) -> None:
    assert pg_connection.in_transaction()
