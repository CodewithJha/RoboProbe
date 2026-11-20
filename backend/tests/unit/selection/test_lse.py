"""Unit smoke for S-LSE (T-058)."""

from __future__ import annotations

from pathlib import Path

import pytest

from roboprobe.scenario.space import ScenarioSpace
from roboprobe.selection.base import StrategyContext
from roboprobe.selection.registry import available, create

pytestmark = [
    pytest.mark.unit,
    pytest.mark.filterwarnings("ignore:.*torch.jit.script.*:FutureWarning"),
]

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_s_lse_registered_and_warms_up() -> None:
    assert "S-LSE" in available()
    space = ScenarioSpace.from_yaml(
        REPO_ROOT / "configs" / "scenario_spaces" / "warehouse_v1.yaml",
        base_dir=REPO_ROOT,
    )
    values = space.nominal_values()
    space = space.with_pins({p.id: values[p.id] for p in space.params[2:]})
    strat = create(
        "S-LSE",
        StrategyContext(space=space, budget=30, seed=0, batch_size=2, params={}),
    )
    proposals = strat.propose([], [], 2)
    assert len(proposals) == 2
    assert all(p.phase == "warmup" for p in proposals)
