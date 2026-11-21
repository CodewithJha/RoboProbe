"""Unit tests for scripts/check_security_map.py (T-109)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_security_map.py"


def _checker():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("check_security_map", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gaps_reports_a_missing_threat() -> None:
    checker = _checker()
    threats = "| TM-01 | API | Spoofing |\n| TM-02 | API | Tampering |\n"
    evidence = "| TM-01 | tests/security/test_tm01_auth.py::test_missing_and_wrong_token | pass |\n"
    assert checker.gaps(threats, evidence) == ["TM-02 has no row in the security-test map"]


def test_gaps_accepts_pass_and_na() -> None:
    checker = _checker()
    threats = "| TM-01 | x |\n| TM-07 | y |\n"
    evidence = (
        "| TM-01 | tests/security/test_tm01_auth.py::test_missing_and_wrong_token | pass |\n"
        "| TM-07 | — | N/A |\n"
    )
    assert checker.gaps(threats, evidence) == []
