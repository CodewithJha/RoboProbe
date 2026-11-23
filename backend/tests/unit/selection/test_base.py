"""Strategy template method: clip, feasibility, dedupe, INVALID, RNG (T-050a)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt
import pytest
from tests.factories import make_observation
from tests.unit.selection.conftest import load_space

from roboprobe.core import errors
from roboprobe.core.types import Observation, Verdict
from roboprobe.scenario.space import Constraint
from roboprobe.selection.base import HISTORY_LINF_TOL, PLUGIN_API_VERSION, Strategy, _linf_dup

pytestmark = pytest.mark.unit

FloatArray = npt.NDArray[np.float64]


class _FixedStrategy(Strategy):
    id = "S-FIXED"

    def __init__(self, ctx: object, points: list[FloatArray]) -> None:
        super().__init__(ctx)  # type: ignore[arg-type]
        self._points = points
        self._i = 0

    def _propose_impl(
        self,
        history: Sequence[Observation],
        pending: Sequence[FloatArray],
        q: int,
        rng: np.random.Generator,
    ) -> list[FloatArray]:
        del history, pending, rng
        out = []
        for _ in range(q):
            out.append(self._points[self._i % len(self._points)].copy())
            self._i += 1
        return out


def _unit(dim: int, fill: float) -> FloatArray:
    return np.full(dim, fill, dtype=np.float64)


def test_plugin_api_version_is_one() -> None:
    assert PLUGIN_API_VERSION == 1
    assert Strategy.PLUGIN_API_VERSION == 1


def test_out_of_bounds_candidates_are_clipped() -> None:
    space, ctx = load_space(dim=2, budget=8)
    raw = _unit(space.dim, 2.0)
    strat = _FixedStrategy(ctx, [raw])
    [proposal] = strat.propose([], [], 1)
    unit = space.to_unit(proposal.scenario.values)
    assert np.all((unit >= 0.0) & (unit <= 1.0))
    np.testing.assert_allclose(unit, np.ones(space.dim))


def test_infeasible_candidates_are_rejected() -> None:
    space, ctx = load_space(dim=2, budget=8)
    space = space.model_copy(update={"constraints": (Constraint(expr="robot.max_speed < 0"),)})
    ctx = ctx.model_copy(update={"space": space, "params": {"max_attempts": 3}})
    strat = _FixedStrategy(ctx, [_unit(space.dim, 0.5)])
    with pytest.raises(errors.StrategyError, match="feasible unique"):
        strat.propose([], [], 1)


def test_duplicates_versus_pending_and_history_are_dropped() -> None:
    space, ctx = load_space(dim=2, budget=8)
    ctx = ctx.model_copy(update={"params": {"max_attempts": 4}})
    point = _unit(space.dim, 0.25)
    other = _unit(space.dim, 0.8)
    strat = _FixedStrategy(ctx, [point, point, other])
    history = [make_observation(x_unit=tuple(float(x) for x in point), robustness=0.1)]
    pending = [point + HISTORY_LINF_TOL / 2]
    [proposal] = strat.propose(history, pending, 1)
    got = space.to_unit(proposal.scenario.values)
    np.testing.assert_allclose(got, other)


def test_batch_pairwise_dedupe() -> None:
    space, ctx = load_space(dim=2, budget=8)
    ctx = ctx.model_copy(update={"params": {"max_attempts": 8}})
    a = _unit(space.dim, 0.1)
    b = _unit(space.dim, 0.9)
    strat = _FixedStrategy(ctx, [a, a, b])
    proposals = strat.propose([], [], 2)
    units = [space.to_unit(p.scenario.values) for p in proposals]
    assert len(proposals) == 2
    assert float(np.max(np.abs(units[0] - units[1]))) > 1e-3


@pytest.mark.parametrize("as_matrix", [False, True])
def test_duplicate_distance_matches_scalar_rule(as_matrix: bool) -> None:
    tol = HISTORY_LINF_TOL
    candidate = np.zeros(2, dtype=np.float64)
    boundary = np.array([tol, -tol])
    just_outside = np.array([np.nextafter(tol, np.inf), 0.0])
    nan_row = np.array([0.0, np.nan])
    for rows in (
        [],
        [boundary],
        [just_outside],
        [nan_row],
        [just_outside, nan_row, boundary],
    ):
        expected = any(float(np.max(np.abs(candidate - row))) <= tol for row in rows)
        points = np.asarray(rows, dtype=np.float64) if as_matrix else rows
        assert _linf_dup(candidate, points, tol) is expected


def test_invalid_observations_do_not_change_proposals() -> None:
    space, ctx = load_space(dim=2, budget=8)
    a = _unit(space.dim, 0.2)
    b = _unit(space.dim, 0.7)
    without = _FixedStrategy(ctx, [a])
    with_invalid = _FixedStrategy(ctx, [a])
    invalid = make_observation(
        x_unit=tuple(float(x) for x in b),
        verdict=Verdict.INVALID,
        robustness=None,
    )
    p0 = without.propose([], [], 1)
    p1 = with_invalid.propose([invalid], [], 1)
    np.testing.assert_allclose(
        space.to_unit(p0[0].scenario.values), space.to_unit(p1[0].scenario.values)
    )


def test_state_dict_default_is_empty_and_json_safe() -> None:
    _, ctx = load_space(dim=2)
    strat = _FixedStrategy(ctx, [_unit(ctx.space.dim, 0.5)])
    assert strat.state_dict() == {}
    strat.load_state_dict({})
    strat.observe(make_observation(x_unit=tuple(0.1 for _ in range(ctx.space.dim))))
    assert strat.is_exhausted() is False


def test_negative_q_is_rejected() -> None:
    _, ctx = load_space(dim=2)
    strat = _FixedStrategy(ctx, [_unit(ctx.space.dim, 0.5)])
    with pytest.raises(errors.ValidationError, match="q"):
        strat.propose([], [], -1)
