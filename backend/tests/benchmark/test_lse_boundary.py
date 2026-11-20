"""S-LSE boundary accuracy vs S-RANDOM (T-058, docs/18 §4.4)."""

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
from roboprobe.selection.benchmarks import multi_mode_6d
from roboprobe.selection.registry import create

pytestmark = [
    pytest.mark.benchmark,
    pytest.mark.slow,
    pytest.mark.filterwarnings("ignore:.*torch.jit.script.*:FutureWarning"),
]

REPO_ROOT = Path(__file__).resolve().parents[3]
SPACE = REPO_ROOT / "configs" / "scenario_spaces" / "multi_mode_6d.yaml"
THRESHOLDS = Path(__file__).resolve().parent / "thresholds.yaml"
SEEDS = tuple(range(int(os.environ.get("ROBOPROBE_BENCH_SEEDS", "10"))))
BOUNDARY_BAND = 0.15


def _thresholds() -> dict[str, float]:
    return dict(yaml.safe_load(THRESHOLDS.read_text(encoding="utf-8"))["lse_boundary"])


def _space() -> ScenarioSpace:
    return ScenarioSpace.from_yaml(SPACE, base_dir=REPO_ROOT)


def _boundary_fraction(strategy_id: str, seed: int, budget: int) -> float:
    space = _space()
    strat = create(
        strategy_id,
        StrategyContext(space=space, budget=budget, seed=seed, batch_size=4, params={}),
    )
    history = []
    near = 0
    while len(history) < budget:
        proposals = strat.propose(history, [], min(4, budget - len(history)))
        if not proposals:
            break
        for proposal in proposals:
            unit = space.to_unit(proposal.scenario.values)
            rho = multi_mode_6d(unit, noise=0.0)
            if abs(rho) < BOUNDARY_BAND:
                near += 1
            verdict = Verdict.FAIL if rho < 0.0 else Verdict.PASS
            history.append(
                make_observation(
                    x_unit=tuple(float(v) for v in unit),
                    robustness=float(rho),
                    verdict=verdict,
                )
            )
    return near / max(len(history), 1)


@pytest.mark.timeout(600)
def test_lse_boundary_accuracy_beats_random() -> None:
    cfg = _thresholds()
    budget = int(cfg["budget"])
    lse = [_boundary_fraction("S-LSE", seed, budget) for seed in SEEDS]
    rnd = [_boundary_fraction("S-RANDOM", seed, budget) for seed in SEEDS]
    assert np.median(lse) >= np.median(rnd) + float(cfg["min_accuracy_gain"])
