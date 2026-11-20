"""Unit tests for ProbeStrategy assembly (T-059c)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from tests.factories import make_observation

from roboprobe.core.types import Verdict
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.selection.base import StrategyContext
from roboprobe.selection.probe import ProbeStrategy
from roboprobe.selection.registry import available, create

pytestmark = [
    pytest.mark.unit,
    pytest.mark.filterwarnings("ignore:.*torch.jit.script.*:FutureWarning"),
]

REPO_ROOT = Path(__file__).resolve().parents[4]
SPACE = REPO_ROOT / "configs" / "scenario_spaces" / "warehouse_v1.yaml"


def _ctx(budget: int = 40, seed: int = 0, dim: int = 2) -> StrategyContext:
    space = ScenarioSpace.from_yaml(SPACE, base_dir=REPO_ROOT)
    if dim < space.dim:
        values = space.nominal_values()
        pins = {p.id: values[p.id] for p in space.params[dim:]}
        space = space.with_pins(pins)
    return StrategyContext(space=space, budget=budget, seed=seed, batch_size=2, params={})


def test_s_probe_registered_as_builtin() -> None:
    assert "S-PROBE" in available()
    assert create("S-PROBE", _ctx()).id == "S-PROBE"


def test_warmup_then_falsify_phases() -> None:
    strat = ProbeStrategy(_ctx())
    first = strat.propose([], [], 2)
    assert len(first) == 2
    assert all(p.phase == "warmup" for p in first)
    history = [
        make_observation(
            x_unit=tuple(float(v) for v in strat.ctx.space.to_unit(p.scenario.values)),
            verdict=Verdict.PASS,
            robustness=0.2,
        )
        for p in first
    ]
    # Drain warm-up.
    while True:
        need = strat._n0 - len(history)
        if need <= 0:
            break
        batch = strat.propose(history, [], min(2, need))
        for p in batch:
            history.append(
                make_observation(
                    x_unit=tuple(float(v) for v in strat.ctx.space.to_unit(p.scenario.values)),
                    verdict=Verdict.PASS,
                    robustness=0.2,
                )
            )
    nxt = strat.propose(history, [], 1)
    assert len(nxt) == 1
    assert nxt[0].phase == "falsify"


def test_state_round_trip_reproduces_next() -> None:
    a = ProbeStrategy(_ctx(seed=5))
    b = ProbeStrategy(_ctx(seed=5))
    first = a.propose([], [], 2)
    b.load_state_dict(a.state_dict())
    hist = [
        make_observation(
            x_unit=tuple(float(v) for v in a.ctx.space.to_unit(p.scenario.values)),
            verdict=Verdict.PASS,
            robustness=0.1,
        )
        for p in first
    ]
    pa = a.propose(hist, [], 2)
    pb = b.propose(hist, [], 2)
    ua = np.stack([a.ctx.space.to_unit(p.scenario.values) for p in pa])
    ub = np.stack([b.ctx.space.to_unit(p.scenario.values) for p in pb])
    np.testing.assert_allclose(ua, ub)
