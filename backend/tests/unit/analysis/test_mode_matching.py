"""Tests for :mod:`roboprobe.analysis.mode_matching` (T-071b)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st
from tests.unit.analysis.conftest import uid

from roboprobe.analysis.mode_matching import match_modes
from roboprobe.analysis.types import FailureModeSummary, ParamRange, StoredMode
from roboprobe.core.types import FailureClass

pytestmark = pytest.mark.unit


def _summary(members: tuple[UUID, ...], code: str = "") -> FailureModeSummary:
    return FailureModeSummary(
        code=code,
        size=len(members),
        primary_class=FailureClass.COL,
        class_mix={FailureClass.COL: 1.0},
        ranges={"robot.max_speed": ParamRange(unit="m/s", q05=0.1, q95=0.2, space_coverage=0.2)},
        characteristic=frozenset({"robot.max_speed"}),
        medoid_run_id=members[0],
        minimal_run_id=members[0],
        minimal_values={},
        member_run_ids=members,
        label="auto",
        provisional=False,
    )


def _stored(
    code: str, members: tuple[UUID, ...], *, user: bool = False, label: str = "auto"
) -> StoredMode:
    return StoredMode(
        id=uuid4(),
        code=code,
        member_run_ids=frozenset(members),
        label=label,
        label_is_user=user,
    )


def test_id_stability_across_perturbation() -> None:
    a = tuple(uid(i) for i in range(1, 6))
    b = tuple(uid(i) for i in range(10, 16))
    prev = [_stored("FM-01", a, user=True, label="user name"), _stored("FM-02", b)]
    new_a = (*a, uid(6))
    matched = match_modes(prev, [_summary(new_a), _summary(b)], 0.5)
    assert matched.new_codes[0] == "FM-01"
    assert matched.new_codes[1] == "FM-02"
    assert matched.preserved_labels[0] == "user name"


def test_order_independent() -> None:
    a = tuple(uid(i) for i in range(1, 5))
    b = tuple(uid(i) for i in range(20, 24))
    prev = [_stored("FM-01", a), _stored("FM-02", b)]
    s1, s2 = _summary(a), _summary(b)
    m1 = match_modes(prev, [s1, s2], 0.5)
    m2 = match_modes(list(reversed(prev)), [s2, s1], 0.5)
    assert m1.new_codes[0] == m2.new_codes[1] == "FM-01"
    assert m1.new_codes[1] == m2.new_codes[0] == "FM-02"


def test_codes_never_reused_across_three_analyses() -> None:
    first = match_modes([], [_summary((uid(1), uid(2)))], 0.5)
    code1 = first.new_codes[0]
    stored = [_stored(code1, (uid(1), uid(2)))]
    second = match_modes(stored, [_summary((uid(10), uid(11)))], 0.5)
    code2 = second.new_codes[0]
    assert code2 != code1
    stored2 = [*stored, _stored(code2, (uid(10), uid(11)))]
    third = match_modes(stored2, [_summary((uid(1), uid(2))), _summary((uid(30), uid(31)))], 0.5)
    assert set(third.new_codes.values()) == {code1, "FM-03"}
    assert code2 not in third.new_codes.values()


def test_threshold_from_settings() -> None:
    a = (uid(1), uid(2), uid(3), uid(4))
    overlap = (uid(1), uid(2), uid(10), uid(11))
    prev = [_stored("FM-01", a)]
    low = match_modes(prev, [_summary(overlap)], 0.2)
    high = match_modes(prev, [_summary(overlap)], 0.9)
    assert low.new_codes[0] == "FM-01"
    assert high.new_codes[0] == "FM-02"


def test_hungarian_tie_stable() -> None:
    a = (uid(1), uid(2))
    b = (uid(3), uid(4))
    prev = [_stored("FM-01", a), _stored("FM-02", b)]
    m1 = match_modes(prev, [_summary(a), _summary(b)], 0.5)
    m2 = match_modes(prev, [_summary(a), _summary(b)], 0.5)
    assert m1.assignments == m2.assignments


@given(
    st.lists(st.integers(1, 50), min_size=1, max_size=5, unique=True),
    st.lists(st.integers(51, 100), min_size=1, max_size=5, unique=True),
)
def test_match_once_or_fresh_code(left: list[int], right: list[int]) -> None:
    prev = [_stored("FM-01", tuple(uid(i) for i in left))]
    new = [_summary(tuple(uid(i) for i in left)), _summary(tuple(uid(i) for i in right))]
    result = match_modes(prev, new, 0.5)
    assert set(result.new_codes) == {0, 1}
    ids = list(result.assignments.values())
    assert len(ids) == len(set(ids))
    assert result.new_codes[0] == "FM-01"
    assert result.new_codes[1] != "FM-01"
