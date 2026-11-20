"""S-BO branin_falsify gate (T-057, docs/18 §4.4)."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
import yaml
from tests.factories import make_observation

from roboprobe.core.types import Verdict
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.selection.base import StrategyContext
from roboprobe.selection.benchmarks import branin_falsify
from roboprobe.selection.registry import create

pytestmark = [
    pytest.mark.benchmark,
    pytest.mark.slow,
    pytest.mark.filterwarnings("ignore:.*torch.jit.script.*:FutureWarning"),
]

REPO_ROOT = Path(__file__).resolve().parents[3]
SPACE = REPO_ROOT / "configs" / "scenario_spaces" / "warehouse_v1.yaml"
THRESHOLDS = Path(__file__).resolve().parent / "thresholds.yaml"
SEEDS = tuple(range(int(os.environ.get("ROBOPROBE_BENCH_SEEDS", "20"))))
BRANIN_DIM = 2


def _thresholds() -> dict[str, float]:
    return dict(yaml.safe_load(THRESHOLDS.read_text(encoding="utf-8"))["bo_branin"])


def _space() -> ScenarioSpace:
    space = ScenarioSpace.from_yaml(SPACE, base_dir=REPO_ROOT)
    values = space.nominal_values()
    pins = {p.id: values[p.id] for p in space.params[BRANIN_DIM:]}
    return space.with_pins(pins)


def _first_fail(seed: int, budget: int) -> int | None:
    space = _space()
    strat = create(
        "S-BO",
        StrategyContext(space=space, budget=budget, seed=seed, batch_size=4, params={}),
    )
    history = []
    while len(history) < budget:
        proposals = strat.propose(history, [], min(4, budget - len(history)))
        if not proposals:
            break
        for proposal in proposals:
            unit = space.to_unit(proposal.scenario.values)
            rho = branin_falsify(unit)
            verdict = Verdict.FAIL if rho < 0.0 else Verdict.PASS
            if verdict is Verdict.FAIL:
                return len(history) + 1
            history.append(
                make_observation(
                    x_unit=tuple(float(v) for v in unit),
                    robustness=float(rho),
                    verdict=verdict,
                )
            )
    return None


@pytest.mark.timeout(600)
def test_bo_median_first_fail_on_branin() -> None:
    cfg = _thresholds()
    budget = int(cfg["budget"])
    first = [ff for seed in SEEDS if (ff := _first_fail(seed, budget)) is not None]
    assert first, "S-BO never found a failure on branin_falsify"
    assert np.median(first) <= float(cfg["median_first_fail_max"])
