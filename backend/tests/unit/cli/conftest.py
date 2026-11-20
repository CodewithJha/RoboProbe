"""Fixtures shared by the CLI unit tests."""

from __future__ import annotations

import sys

import pytest

from roboprobe.core.logging import configure_logging
from roboprobe.core.settings import LoggingSettings


@pytest.fixture(autouse=True)
def plain_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make Rich render CLI output without ANSI styling, whatever the caller's terminal.

    Typer forces a Rich terminal when ``GITHUB_ACTIONS`` or ``FORCE_COLOR`` is set (e.g. in CI),
    which splits option names in ``--help`` output with escape codes. ``TERM=dumb`` disables
    styling at render time, so assertions on plain text hold everywhere.
    """
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("NO_COLOR", "1")


@pytest.fixture(autouse=True)
def _reset_structlog_after_clirunner() -> None:
    """Rebind structlog after CliRunner closes its capture stream (xdist pollution)."""
    configure_logging(LoggingSettings(), "test-cli", "0.0.0", stream=sys.stderr)
    yield
    configure_logging(LoggingSettings(), "test-cli", "0.0.0", stream=sys.stderr)
