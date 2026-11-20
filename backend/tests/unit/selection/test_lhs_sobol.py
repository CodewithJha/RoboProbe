"""S-LHS and S-SOBOL space-filling baselines (T-051b)."""

from __future__ import annotations

import numpy as np
import pytest
from tests.factories import make_observation
from tests.unit.selection.conftest import load_space

from roboprobe.core.seeding import STRATEGY, derive_seed, make_rng
from roboprobe.scenario.samplers import LatinHypercubeSampler, SobolSampler
from roboprobe.selection.baselines.lhs import LHSStrategy
from roboprobe.selection.baselines.sobol import SobolStrategy

pytestmark = pytest.mark.unit


def _units(space, proposals):
    return np.stack([space.to_unit(p.scenario.values) for p in proposals])


def test_lhs_matches_sampler_and_is_stratified() -> None:
    space, ctx = load_space(dim=2, budget=16, seed=5)
    strat = LHSStrategy(ctx)
    proposals = strat.propose([], [], ctx.budget)
    expected = LatinHypercubeSampler(space.dim).sample(ctx.budget, make_rng(ctx.seed, STRATEGY))
    got = _units(space, proposals)
    np.testing.assert_allclose(got, expected)
    for j in range(space.dim):
        assert sorted(np.floor(got[:, j] * ctx.budget).astype(int)) == list(range(ctx.budget))
    assert strat.is_exhausted()
    assert strat.propose([], [], 1) == []


def test_lhs_state_round_trip_continues_design() -> None:
    space, ctx = load_space(dim=2, budget=12, seed=1)
    a = LHSStrategy(ctx)
    first = a.propose([], [], 4)
    b = LHSStrategy(ctx)
    b.load_state_dict(a.state_dict())
    hist = [
        make_observation(x_unit=tuple(float(x) for x in space.to_unit(p.scenario.values)))
        for p in first
    ]
    rest_a = a.propose(hist, [], 4)
    rest_b = b.propose(hist, [], 4)
    np.testing.assert_allclose(_units(space, rest_a), _units(space, rest_b))


def test_sobol_prefix_balance_and_resume() -> None:
    space, ctx = load_space(dim=2, budget=32, seed=9)
    n = 16
    strat = SobolStrategy(ctx)
    proposals = strat.propose([], [], n)
    engine = SobolSampler(space.dim, seed=derive_seed(ctx.seed, STRATEGY))
    expected = engine.sample(n, np.random.default_rng(0))
    got = _units(space, proposals)
    np.testing.assert_allclose(got, expected)
    for j in range(space.dim):
        assert sorted(np.floor(got[:, j] * n).astype(int)) == list(range(n))

    other = SobolStrategy(ctx)
    other.load_state_dict(strat.state_dict())
    nxt = other.propose([], [], 8)
    np.testing.assert_allclose(_units(space, nxt), engine.sample(8, np.random.default_rng(0)))
