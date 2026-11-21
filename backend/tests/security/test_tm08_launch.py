"""TM-08: scenario values are not passed to a shell (T-109).

Gazebo launch files are not built yet (T-094). The control that exists is that product
code never calls ``subprocess`` with ``shell=True``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.security

_SRC = Path(__file__).resolve().parents[2] / "src" / "roboprobe"


def test_no_shell_true_in_product_code() -> None:
    offenders = [
        path.relative_to(_SRC).as_posix()
        for path in _SRC.rglob("*.py")
        if "shell=True" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
