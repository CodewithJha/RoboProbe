"""Shared helpers for selection unit tests."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from roboprobe.scenario.space import ScenarioSpace
from roboprobe.selection.base import StrategyContext

# Silence Torch JIT deprecation from BoTorch/GPyTorch under warnings=error.
warnings.filterwarnings("ignore", message=r".*torch\.jit\.script.*", category=FutureWarning)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
WAREHOUSE = REPO_ROOT / "configs" / "scenario_spaces" / "warehouse_v1.yaml"


def load_space(
    *, dim: int = 6, budget: int = 32, seed: int = 0
) -> tuple[ScenarioSpace, StrategyContext]:
    space = ScenarioSpace.from_yaml(WAREHOUSE, base_dir=REPO_ROOT)
    if dim < space.dim:
        values = space.nominal_values()
        pins = {p.id: values[p.id] for p in space.params[dim:]}
        space = space.with_pins(pins)
    ctx = StrategyContext(space=space, budget=budget, seed=seed, batch_size=4, params={})
    return space, ctx
