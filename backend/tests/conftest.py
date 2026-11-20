"""Shared pytest configuration for the RoboProbe backend test suite (docs/18).

Fixtures that are useful across test layers live here; layer-specific fixtures live in the
``conftest.py`` of each test directory. Domain objects come from :mod:`tests.factories`.

Hypothesis profiles (select with ``HYPOTHESIS_PROFILE``; default ``dev``):

* ``dev``: Hypothesis defaults, fast local feedback.
* ``ci``: 200 examples per property, no deadline (shared runners have noisy timing).
* ``nightly``: 2000 examples per property, no deadline.

PostgreSQL fixtures (``postgres_url``, ``pg_engine``, ``pg_connection``) are defined here so
both ``integration`` and ``e2e`` layers share them (docs/18 §2).
"""

from __future__ import annotations

import gc
import os
import warnings
from collections.abc import Iterator

import pytest
from hypothesis import HealthCheck, settings
from sqlalchemy import Connection, Engine, create_engine

HYPOTHESIS_PROFILE_ENV = "HYPOTHESIS_PROFILE"
DEFAULT_HYPOTHESIS_PROFILE = "dev"
CI_MAX_EXAMPLES = 200
NIGHTLY_MAX_EXAMPLES = 2000

TEST_DATABASE_URL_ENV = "ROBOPROBE_TEST_DATABASE_URL"
POSTGRES_IMAGE = "postgres:17"
"""Major version pinned to production (docs/15 §1, ADR on PostgreSQL)."""
SQLALCHEMY_DRIVER = "psycopg"
"""psycopg 3, the driver used by the application (backend/pyproject.toml)."""

settings.register_profile(DEFAULT_HYPOTHESIS_PROFILE)
settings.register_profile(
    "ci",
    max_examples=CI_MAX_EXAMPLES,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "nightly",
    max_examples=NIGHTLY_MAX_EXAMPLES,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get(HYPOTHESIS_PROFILE_ENV, DEFAULT_HYPOTHESIS_PROFILE))


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
