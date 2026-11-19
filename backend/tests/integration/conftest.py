"""Integration tests against real infrastructure (PostgreSQL via Testcontainers, filesystem).

Fixtures specific to this test layer go here (docs/18 §2).

Database selection, in order:

1. ``ROBOPROBE_TEST_DATABASE_URL`` (SQLAlchemy URL), e.g. a CI service container; never a
   database holding data you care about, tests create and roll back objects in it.
2. A throw-away ``postgres:17`` Testcontainers container started once per session (per
   ``pytest-xdist`` worker).
3. Otherwise every test that needs the database is skipped with the reason.

``pg_connection`` wraps each test in a transaction that is rolled back afterwards, so tests are
isolated from each other without truncating tables.
"""

from __future__ import annotations

import gc
import os
import warnings
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, create_engine

TEST_DATABASE_URL_ENV = "ROBOPROBE_TEST_DATABASE_URL"
POSTGRES_IMAGE = "postgres:17"
"""Major version pinned to production (docs/15 §1, ADR on PostgreSQL)."""
SQLALCHEMY_DRIVER = "psycopg"
"""psycopg 3, the driver used by the application (backend/pyproject.toml)."""


def _docker_unavailable_reason() -> str | None:
    """Return why Docker cannot be used, or ``None`` if the daemon answers."""
    import docker  # noqa: PLC0415 - only needed when no database URL override is set
    from docker.errors import DockerException  # noqa: PLC0415

    # A failed docker.from_env() leaves a half-built client whose socket is only reclaimed by the
    # garbage collector; collect it here with ResourceWarning silenced so it cannot surface later
    # as an unrelated "unraisable exception" error under ``filterwarnings = error``.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ResourceWarning)
        try:
            client = docker.from_env()
        except DockerException as exc:
            reason: str | None = f"Docker daemon unavailable ({exc.__class__.__name__})"
        else:
            with client:
                client.ping()
            reason = None
        gc.collect()
    if reason is None:
        return None
    return f"{reason}; start Docker or set {TEST_DATABASE_URL_ENV}"


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """SQLAlchemy URL of a PostgreSQL 17 database for this test session."""
    override = os.environ.get(TEST_DATABASE_URL_ENV)
    if override:
        yield override
        return
    reason = _docker_unavailable_reason()
    if reason is not None:
        pytest.skip(reason)
    from testcontainers.community.postgres import PostgresContainer  # noqa: PLC0415

    with PostgresContainer(POSTGRES_IMAGE, driver=SQLALCHEMY_DRIVER) as container:
        yield container.get_connection_url()


@pytest.fixture(scope="session")
def pg_engine(postgres_url: str) -> Iterator[Engine]:
    """Session-wide SQLAlchemy engine bound to :func:`postgres_url`."""
    engine = create_engine(postgres_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def pg_connection(pg_engine: Engine) -> Iterator[Connection]:
    """A connection inside a transaction that is rolled back after the test (isolation)."""
    with pg_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()
