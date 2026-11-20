"""Oracle registry API version gate (T-036a)."""

from __future__ import annotations

import pytest

from roboprobe.core.errors import PluginError
from roboprobe.core.settings import OracleThresholds
from roboprobe.core.types import FailureClass, OracleResult, TaskSpec, Trace
from roboprobe.oracles.base import Oracle
from roboprobe.oracles.registry import OracleRegistry, create_all

pytestmark = pytest.mark.unit


class _BadApi(Oracle):
    PLUGIN_API_VERSION = 0
    id = "O-BAD"
    failure_class = FailureClass.COL
    severity = "failure"

    def evaluate(self, trace: Trace, task: TaskSpec) -> OracleResult:
        raise AssertionError


def test_create_all_builtin_ids() -> None:
    oracles = create_all(OracleThresholds())
    assert [o.id for o in oracles] == [
        "O-CLEAR",
        "O-GOAL",
        "O-PROG",
        "O-LOC",
        "O-NAV",
        "O-STAB",
        "O-OSC",
    ]


def test_rejects_api_mismatch() -> None:
    with pytest.raises(PluginError, match="PLUGIN_API_VERSION"):
        OracleRegistry(extra={"O-BAD": _BadApi})
