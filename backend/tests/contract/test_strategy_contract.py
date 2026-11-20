"""Strategy contract suite over every registered plugin (T-050b, docs/18 §4.3)."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest
from tests.factories import make_observation

from roboprobe.core.settings.selection import SelectionDefaults
from roboprobe.core.types import Verdict
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.selection.base import HISTORY_LINF_TOL, StrategyContext
from roboprobe.selection.registry import available, create

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
WAREHOUSE = REPO_ROOT / "configs" / "scenario_spaces" / "warehouse_v1.yaml"
CONTRACT_BUDGET = 16
CONTRACT_Q = 4


def _space(dim: int) -> ScenarioSpace:
    space = ScenarioSpace.from_yaml(WAREHOUSE, base_dir=REPO_ROOT)
    if dim < space.dim:
        values = space.nominal_values()
        pins = {p.id: values[p.id] for p in space.params[dim:]}
        space = space.with_pins(pins)
    return space


def _ctx(dim: int, seed: int = 7) -> StrategyContext:
    return StrategyContext(
        space=_space(dim), budget=CONTRACT_BUDGET, seed=seed, batch_size=CONTRACT_Q, params={}
    )


def _units(space: ScenarioSpace, proposals: Sequence[object]) -> np.ndarray:
    return np.stack([space.to_unit(p.scenario.values) for p in proposals])  # type: ignore[attr-defined]


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "strategy_id" in metafunc.fixturenames:
        metafunc.parametrize("strategy_id", available())


@pytest.mark.parametrize("dim", [2, 6])
def test_proposals_in_bounds_feasible_and_sized(strategy_id: str, dim: int) -> None:
    ctx = _ctx(dim)
    strat = create(strategy_id, ctx)
    proposals = strat.propose([], [], CONTRACT_Q)
    assert 0 < len(proposals) <= CONTRACT_Q
    if not strat.is_exhausted():
        assert len(proposals) == CONTRACT_Q
    space = ctx.space
    for proposal in proposals:
        unit = space.to_unit(proposal.scenario.values)
        assert np.all((unit >= 0.0) & (unit <= 1.0))
        values = {**space.nominal_values(), **space.from_unit(unit)}
        assert space.is_feasible(values)
        assert proposal.strategy == strategy_id


@pytest.mark.parametrize("dim", [2])
def test_determinism_with_seed(strategy_id: str, dim: int) -> None:
    ctx = _ctx(dim, seed=21)
    a = _units(ctx.space, create(strategy_id, ctx).propose([], [], CONTRACT_Q))
    b = _units(ctx.space, create(strategy_id, ctx).propose([], [], CONTRACT_Q))
    np.testing.assert_allclose(a, b)


@pytest.mark.parametrize("dim", [2])
def test_no_duplicates_with_pending(strategy_id: str, dim: int) -> None:
    ctx = _ctx(dim)
    live = create(strategy_id, ctx)
    first = live.propose([], [], CONTRACT_Q)
    second = live.propose([], list(_units(ctx.space, first)), CONTRACT_Q)
    if not second or live._allow_repeats:
        return
    first_u = _units(ctx.space, first)
    for row in _units(ctx.space, second):
        assert all(float(np.max(np.abs(row - prev))) > HISTORY_LINF_TOL for prev in first_u)


@pytest.mark.parametrize("dim", [2])
def test_ignores_invalid_history(strategy_id: str, dim: int) -> None:
    ctx = _ctx(dim)
    invalid = make_observation(
        x_unit=tuple(0.5 for _ in range(dim)),
        verdict=Verdict.INVALID,
        robustness=None,
    )
    a = _units(ctx.space, create(strategy_id, ctx).propose([], [], CONTRACT_Q))
    b = _units(ctx.space, create(strategy_id, ctx).propose([invalid], [], CONTRACT_Q))
    np.testing.assert_allclose(a, b)


@pytest.mark.parametrize("dim", [2])
def test_state_dict_round_trip(strategy_id: str, dim: int) -> None:
    ctx = _ctx(dim)
    live = create(strategy_id, ctx)
    first = live.propose([], [], CONTRACT_Q)
    blob = json.loads(json.dumps(live.state_dict()))
    clone = create(strategy_id, ctx)
    clone.load_state_dict(blob)
    hist = [
        make_observation(x_unit=tuple(float(x) for x in ctx.space.to_unit(p.scenario.values)))
        for p in first
    ]
    a = live.propose(hist, [], CONTRACT_Q)
    b = clone.propose(hist, [], CONTRACT_Q)
    if not a and not b:
        return
    np.testing.assert_allclose(_units(ctx.space, a), _units(ctx.space, b))


@pytest.mark.parametrize("dim", [2])
def test_propose_timeout(strategy_id: str, dim: int) -> None:
    ctx = _ctx(dim)
    strat = create(strategy_id, ctx)
    t0 = time.perf_counter()
    strat.propose([], [], CONTRACT_Q)
    elapsed = time.perf_counter() - t0
    assert elapsed < SelectionDefaults().propose_timeout_s
