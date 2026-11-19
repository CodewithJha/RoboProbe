"""Fixtures for ``roboprobe.core`` unit tests."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def settings_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Hermetic settings environment: no ``ROBOPROBE_*`` vars, empty cwd and secrets dir.

    Yields:
        The temporary working directory (place ``.env`` / ``roboprobe.toml`` here).
    """
    for name in list(os.environ):
        if name.upper().startswith("ROBOPROBE_"):
            monkeypatch.delenv(name)
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    monkeypatch.setenv("ROBOPROBE_SECRETS_DIR", str(secrets))
    monkeypatch.chdir(tmp_path)
    yield tmp_path
