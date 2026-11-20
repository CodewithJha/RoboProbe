"""S-PROBE multi_mode_6d gates (T-059c, docs/07 §9, docs/18 §4.4)."""

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
from roboprobe.selection.benchmarks import label_mode, multi_mode_6d
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
MULTI_DIM = 6


def _thresholds() -> dict[str, float]:
    raw = yaml.safe_load(THRESHOLDS.read_text(encoding="utf-8"))
    return dict(raw["probe_multimode"])


def _space() -> ScenarioSpace:
    space = ScenarioSpace.from_yaml(SPACE, base_dir=REPO_ROOT)
    if space.dim > MULTI_DIM:
        values = space.nominal_values()
        pins = {p.id: values[p.id] for p in space.params[MULTI_DIM:]}
        space = space.with_pins(pins)
    return space


def _run_seed(strategy_id: str, seed: int, budget: int) -> tuple[int | None, set[str]]:
    space = _space()
    ctx = StrategyContext(space=space, budget=budget, seed=seed, batch_size=4, params={})
    strat = create(strategy_id, ctx)
    history = []
    first_fail: int | None = None
    modes: set[str] = set()
    while len(history) < budget:
        q = min(4, budget - len(history))
        proposals = strat.propose(history, [], q)
        if not proposals:
            break
        for proposal in proposals:
            unit = space.to_unit(proposal.scenario.values)
            rho = multi_mode_6d(unit, noise=0.0)
            verdict = Verdict.FAIL if rho < 0.0 else Verdict.PASS
            if verdict is Verdict.FAIL and first_fail is None:
                first_fail = len(history) + 1
            label = label_mode(unit)
            if label is not None:
                modes.add(label)
            obs = make_observation(
                x_unit=tuple(float(v) for v in unit),
                robustness=float(rho),
                verdict=verdict,
            )
            history.append(obs)
            strat.observe(obs)
    return first_fail, modes


@pytest.mark.timeout(600)
def test_probe_finds_modes_and_beats_random_median() -> None:
    cfg = _thresholds()
    budget = int(cfg["budget"])
    probe_first: list[int] = []
    random_first: list[int] = []
    mode_hits = 0
    for seed in SEEDS:
        ff, modes = _run_seed("S-PROBE", seed, budget)
        if ff is not None:
            probe_first.append(ff)
        if len(modes) >= int(cfg["min_modes"]):
            mode_hits += 1
        rf, _ = _run_seed("S-RANDOM", seed, budget)
        if rf is not None:
            random_first.append(rf)
    assert mode_hits / len(SEEDS) >= float(cfg["success_fraction"])
    assert np.median(probe_first) <= float(cfg["first_fail_ratio_vs_random"]) * np.median(
        random_first
    )
