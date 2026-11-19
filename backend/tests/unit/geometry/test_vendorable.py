"""``roboprobe.geometry`` is vendored into the ROS package, so it may import only NumPy/SciPy."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

import roboprobe.geometry

pytestmark = pytest.mark.unit

ALLOWED_THIRD_PARTY = {"numpy", "scipy"}
PACKAGE_DIR = Path(roboprobe.geometry.__file__).parent


def imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module)
    return roots


@pytest.mark.parametrize("path", sorted(PACKAGE_DIR.glob("*.py")), ids=lambda p: p.name)
def test_only_stdlib_numpy_scipy_and_itself(path: Path) -> None:
    for module in imported_roots(path):
        top = module.split(".")[0]
        allowed = (
            top in sys.stdlib_module_names
            or top in ALLOWED_THIRD_PARTY
            or module.startswith("roboprobe.geometry")
        )
        assert allowed, f"{path.name} imports {module}"
