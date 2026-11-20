"""S-CEM plugin contract smoke (T-062)."""

from __future__ import annotations

from pathlib import Path

import pytest

from roboprobe.scenario.space import ScenarioSpace
from roboprobe.selection.base import StrategyContext
from roboprobe.selection.registry import available, create

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_s_cem_loaded_via_entry_point() -> None:
    assert "S-CEM" in available()
    space = ScenarioSpace.from_yaml(
        REPO_ROOT / "configs" / "scenario_spaces" / "warehouse_v1.yaml",
        base_dir=REPO_ROOT,
    )
    values = space.nominal_values()
    space = space.with_pins({p.id: values[p.id] for p in space.params[2:]})
    strat = create(
        "S-CEM",
        StrategyContext(space=space, budget=40, seed=1, batch_size=4, params={}),
    )
    proposals = strat.propose([], [], 4)
    assert len(proposals) == 4
    assert all(p.strategy == "S-CEM" for p in proposals)
