"""Fixtures for CLI tests."""

from collections.abc import Iterator

import pytest
import structlog


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    """Commands configure process-wide logging; undo it so tests stay independent."""
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
