"""S-GRID: full-factorial grid, optionally a seeded subset of size B (docs/07 §3).

Implements: FR-SEL-001, PR-04
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, ClassVar

import numpy as np

from roboprobe.core.seeding import STRATEGY, make_rng
from roboprobe.core.types import Observation
from roboprobe.scenario.samplers import GridSampler
from roboprobe.selection.base import FloatArray, Strategy, StrategyContext

__all__ = ["GridStrategy"]


class GridStrategy(Strategy):
    """Finite grid; ``is_exhausted`` after the consumed design is spent."""

    id: ClassVar[str] = "S-GRID"

    def __init__(self, ctx: StrategyContext) -> None:
        """Start at the beginning of the grid (or its seeded subset)."""
        super().__init__(ctx)
        self._index = 0
        self._design: FloatArray | None = None

    def _design_points(self) -> FloatArray:
        if self._design is None:
            dim = self.ctx.space.dim
            min_levels = self.ctx.selection.grid.min_levels
            k = max(min_levels, math.floor(max(self.ctx.budget, 1) ** (1 / dim)))
            sampler = GridSampler(dim, k)
            if sampler.size > self.ctx.budget:
                rng = make_rng(self.ctx.seed, STRATEGY)
                self._design = sampler.sample(self.ctx.budget, rng)
            else:
                self._design = sampler.points()
        return self._design

    def is_exhausted(self) -> bool:
        """True after every stored grid point has been proposed."""
        return bool(self._index >= self._design_points().shape[0])

    def _propose_impl(
        self,
        history: Sequence[Observation],
        pending: Sequence[FloatArray],
        q: int,
        rng: np.random.Generator,
    ) -> list[FloatArray]:
        del history, pending, rng
        design = self._design_points()
        take = min(q, design.shape[0] - self._index)
        if take <= 0:
            return []
        sl = design[self._index : self._index + take]
        self._index += take
        return [sl[i].copy() for i in range(sl.shape[0])]

    def state_dict(self) -> dict[str, Any]:
        """Index into the grid (or its seeded permutation)."""
        return {"index": self._index}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        """Restore consume index."""
        self._index = int(state.get("index", 0))
        self._design = None
