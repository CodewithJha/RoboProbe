"""Stop rules and auto-pause predicates (T-042b)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from roboprobe.core.settings.runner import RunnerSettings
from roboprobe.core.types import RunStatus, Verdict
from roboprobe.runner.stop_rules import (
    CampaignCounters,
    counters_from_runs,
    evaluate_stop_rules,
)

pytestmark = pytest.mark.unit


def _counters(**kwargs: object) -> CampaignCounters:
    base: dict[str, object] = {
        "budget": 100,
        "finished": 0,
        "invalid": 0,
        "consecutive_invalid": 0,
        "modes_found": 0,
        "started_at": datetime(2020, 1, 1, tzinfo=UTC),
        "now": datetime(2020, 1, 1, tzinfo=UTC),
        "stop_rules": {},
    }
    base.update(kwargs)
    return CampaignCounters(**base)  # type: ignore[arg-type]


def test_budget_exhausted() -> None:
    d = evaluate_stop_rules(_counters(finished=100, budget=100), RunnerSettings())
    assert d.action == "analyze"
    assert d.code == "BUDGET_EXHAUSTED"


def test_max_modes_and_wall() -> None:
    settings = RunnerSettings()
    d = evaluate_stop_rules(_counters(modes_found=3, stop_rules={"max_modes": 3}), settings)
    assert d.action == "analyze" and d.code == "MAX_MODES"
    start = datetime(2020, 1, 1, tzinfo=UTC)
    d = evaluate_stop_rules(
        _counters(
            started_at=start,
            now=start + timedelta(seconds=100),
            stop_rules={"max_wall_s": 50},
        ),
        settings,
    )
    assert d.action == "analyze" and d.code == "MAX_WALL"


def test_invalid_ratio_and_consecutive() -> None:
    settings = RunnerSettings()
    d = evaluate_stop_rules(_counters(finished=20, invalid=5), settings)
    assert d.action == "pause" and d.code == "INFRA_UNHEALTHY"
    d = evaluate_stop_rules(_counters(finished=5, invalid=5, consecutive_invalid=10), settings)
    assert d.action == "pause" and d.code == "INFRA_UNHEALTHY"


def test_counters_from_runs_streak() -> None:
    runs = [
        SimpleNamespace(status=RunStatus.DONE, verdict=Verdict.PASS),
        SimpleNamespace(status=RunStatus.ERROR, verdict=Verdict.INVALID),
        SimpleNamespace(status=RunStatus.DONE, verdict=Verdict.INVALID),
        SimpleNamespace(status=RunStatus.DONE, verdict=Verdict.PASS),
    ]
    c = counters_from_runs(
        budget=10,
        runs=runs,
        modes_found=0,
        started_at=None,
        now=datetime(2020, 1, 1, tzinfo=UTC),
        stop_rules={},
    )
    assert c.finished == 4
    assert c.invalid == 2
    assert c.consecutive_invalid == 0
