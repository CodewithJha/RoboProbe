"""S-RANDOM baseline (T-051a)."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats
from tests.unit.selection.conftest import load_space

from roboprobe.core.seeding import STRATEGY, make_rng
from roboprobe.scenario.normalize import from_unit_batch
from roboprobe.scenario.samplers import PriorSampler
from roboprobe.selection.baselines.random import RandomStrategy

pytestmark = pytest.mark.unit

KS_ALPHA = 0.01
N_STAT = 800


def test_matches_prior_sampler_stream() -> None:
    space, ctx = load_space(dim=6, budget=64, seed=11)
    strat = RandomStrategy(ctx)
    proposals = strat.propose([], [], 16)
    expected = PriorSampler(space.params).sample(16, make_rng(ctx.seed, STRATEGY, 0))
    got = np.stack([space.to_unit(p.scenario.values) for p in proposals])
    np.testing.assert_allclose(got, expected)
    assert strat.state_dict()["n_draws"] == 16


def test_marginal_ks_versus_prior() -> None:
    space, ctx = load_space(dim=6, budget=N_STAT, seed=3)
    strat = RandomStrategy(ctx)
    proposals = strat.propose([], [], N_STAT)
    unit = np.stack([space.to_unit(p.scenario.values) for p in proposals])
    decoded = from_unit_batch(space.params, unit)
    for spec in space.params:
        if spec.prior.kind != "uniform":
            continue
        values = np.array([row[spec.id] for row in decoded], dtype=np.float64)
        low, high = float(spec.low or 0), float(spec.high or 1)
        scaled = (values - low) / (high - low)
        assert stats.kstest(scaled, "uniform").pvalue > KS_ALPHA


def test_resume_n_draws() -> None:
    _, ctx = load_space(seed=2)
    a = RandomStrategy(ctx)
    a.propose([], [], 4)
    b = RandomStrategy(ctx)
    b.load_state_dict(a.state_dict())
    assert b.state_dict()["n_draws"] == 4
