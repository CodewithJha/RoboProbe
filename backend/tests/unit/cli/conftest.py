"""Fixtures shared by the CLI unit tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def plain_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make Rich render CLI output without ANSI styling, whatever the caller's terminal.

    Typer forces a Rich terminal when ``GITHUB_ACTIONS`` or ``FORCE_COLOR`` is set (e.g. in CI),
    which splits option names in ``--help`` output with escape codes. ``TERM=dumb`` disables
    styling at render time, so assertions on plain text hold everywhere.
    """
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("NO_COLOR", "1")
