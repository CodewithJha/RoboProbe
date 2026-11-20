"""Tests for :mod:`roboprobe.analysis.rules` (T-073, docs/09 §4.3)."""

from __future__ import annotations

import pytest
from tests.unit.analysis.synthetic import planted_threshold

from roboprobe.analysis.modes import denormalize_param
from roboprobe.analysis.rules import RuleExtractor, _merge_conditions, render_rule
from roboprobe.analysis.settings import RuleExtractorSettings
from roboprobe.analysis.types import Condition
from roboprobe.core.types import FailureClass
from roboprobe.scenario.space import ParameterSpec

pytestmark = pytest.mark.unit

_MAX_CONDITIONS = 4


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ([(0, "<", 0.4), (0, "<", 0.2)], [(0, "<", 0.2)]),
        ([(0, "≥", 0.1), (0, "≥", 0.3)], [(0, "≥", 0.3)]),
        ([(0, "<", 0.8), (1, "≥", 0.2), (0, "<", 0.5)], [(0, "<", 0.5), (1, "≥", 0.2)]),
    ],
)
def test_condition_merging(
    raw: list[tuple[int, str, float]], expected: list[tuple[int, str, float]]
) -> None:
    merged = _merge_conditions(raw)  # type: ignore[arg-type]
    assert merged == expected


def test_planted_threshold_recovered(space: object) -> None:
    x, y, _names = planted_threshold(400, space.dim, seed=2, cut=0.4)  # type: ignore[union-attr]
    names = [spec.id for spec in space.params]  # type: ignore[union-attr]
    rules = RuleExtractor(RuleExtractorSettings(max_depth=2, min_precision=0.6), seed=0).extract(
        x,
        y,
        names,
        space,  # type: ignore[arg-type]
    )
    assert rules
    speed_conds = [c for r in rules for c in r.conditions if c.param == "robot.max_speed"]
    assert speed_conds
    assert any(abs(c.threshold_unit - 0.4) <= 0.05 for c in speed_conds)


def test_rule_text_and_sort(space: object) -> None:
    cond = Condition(
        param="robot.max_speed",
        op="≥",
        threshold_unit=0.7,
        threshold_physical=0.38,
        unit="m/s",
    )
    text = render_rule([cond], 0.83, 41, FailureClass.COL)
    assert text.startswith("IF robot.max_speed > 0.38 m/s THEN FAIL")
    assert "precision 0.83" in text
    x, y, names = planted_threshold(200, space.dim, seed=3, cut=0.35)  # type: ignore[union-attr]
    names = [spec.id for spec in space.params]  # type: ignore[union-attr]
    rules = RuleExtractor(RuleExtractorSettings(), seed=1).extract(x, y, names, space)  # type: ignore[arg-type]
    scores = [r.precision * r.support for r in rules]
    assert scores == sorted(scores, reverse=True)
    assert all(len(r.conditions) <= _MAX_CONDITIONS for r in rules)


def test_log_scale_physical_units(space: object) -> None:
    spec: ParameterSpec = space.param("env.illuminance")  # type: ignore[union-attr]
    assert spec.scale == "log"
    low = float(denormalize_param(spec, 0.0))
    high = float(denormalize_param(spec, 1.0))
    assert low == pytest.approx(spec.low)
    assert high == pytest.approx(spec.high)
