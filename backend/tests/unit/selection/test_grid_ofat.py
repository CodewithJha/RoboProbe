"""S-GRID and S-OFAT predefined baselines (T-051c)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from tests.unit.selection.conftest import load_space

from roboprobe.core.settings.selection import SelectionDefaults
from roboprobe.selection.baselines.grid import GridStrategy
from roboprobe.selection.baselines.ofat import OFATStrategy

pytestmark = pytest.mark.unit


def _units(space, proposals):
    return np.stack([space.to_unit(p.scenario.values) for p in proposals])


def test_grid_permutation_when_design_exceeds_budget() -> None:
    space, ctx = load_space(dim=6, budget=10, seed=4)
    strat = GridStrategy(ctx)
    k = max(SelectionDefaults().grid.min_levels, math.floor(ctx.budget ** (1 / space.dim)))
    assert k == 2
    assert k**space.dim > ctx.budget
    proposals = strat.propose([], [], ctx.budget)
    assert len(proposals) == ctx.budget
    assert strat.is_exhausted()
    units = _units(space, proposals)
    assert len({tuple(np.round(row, 12)) for row in units}) == ctx.budget
    assert strat.propose([], [], 3) == []


def test_grid_lex_order_when_small_enough() -> None:
    space, ctx = load_space(dim=2, budget=16, seed=0)
    strat = GridStrategy(ctx)
    proposals = strat.propose([], [], 16)
    units = _units(space, proposals)
    assert units.shape[0] == 16
    np.testing.assert_allclose(units[0], [0.0, 0.0])
    np.testing.assert_allclose(units[-1], [1.0, 1.0])
    assert strat.is_exhausted()


def test_ofat_distinct_count_and_cycle() -> None:
    space, ctx = load_space(dim=6, budget=40, seed=0)
    levels = SelectionDefaults().ofat.levels
    expected = space.dim * len(levels)
    strat = OFATStrategy(ctx)
    first = strat.propose([], [], expected)
    units = _units(space, first)
    unique = {tuple(np.round(row, 12)) for row in units}
    assert len(unique) == expected
    assert expected == 30
    wrapped = strat.propose([], [], 3)
    assert len(wrapped) == 3
    np.testing.assert_allclose(_units(space, wrapped), units[:3])
    assert strat._allow_repeats is True
