"""Deliberately failing test to prove CI fails (reverted in the next commit)."""

import pytest

pytestmark = pytest.mark.unit


def test_ci_must_fail() -> None:
    """Always fails."""
    assert 1 == 2  # noqa: PLR0133
