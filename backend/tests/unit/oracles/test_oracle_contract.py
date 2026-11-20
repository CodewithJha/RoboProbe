"""Oracle port contract: robustness bounds and purity (T-036a; docs/18 §4.3)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from tests.factories import make_trace
from tests.unit.oracles.conftest import make_task

from roboprobe.core.settings import OracleThresholds
from roboprobe.oracles import Oracle, create_all
from roboprobe.oracles.base import Oracle as OracleBase

pytestmark = pytest.mark.contract

THRESHOLDS = OracleThresholds()
TASK = make_task()
TRACE = make_trace(n=80, dt=0.1, speed=0.5, goal=(4.0, 0.0))


@pytest.mark.parametrize("oracle", create_all(THRESHOLDS), ids=lambda o: o.id)
def test_robustness_in_unit_interval(oracle: Oracle) -> None:
    r = oracle.evaluate(TRACE, TASK)
    assert -1.0 <= r.robustness <= 1.0
    if r.severity == "failure":
        assert r.violated is (r.robustness < 0.0)


@pytest.mark.parametrize("oracle", create_all(THRESHOLDS), ids=lambda o: o.id)
def test_pure_no_io(oracle: Oracle) -> None:
    with (
        patch("builtins.open", side_effect=AssertionError("open")),
        patch("socket.socket", side_effect=AssertionError("socket")),
    ):
        a = oracle.evaluate(TRACE, TASK)
        b = oracle.evaluate(TRACE, TASK)
    assert a == b


def test_plugin_api_version() -> None:
    assert OracleBase.PLUGIN_API_VERSION == 1
    for oracle in create_all(THRESHOLDS):
        assert oracle.PLUGIN_API_VERSION == OracleBase.PLUGIN_API_VERSION
