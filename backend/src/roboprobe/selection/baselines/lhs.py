"""S-LHS: one Latin hypercube of size B, consumed in order (docs/07 §3).

Implements: FR-SEL-001, PR-04
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

import numpy as np

from roboprobe.core.seeding import STRATEGY, make_rng
from roboprobe.core.types import Observation
from roboprobe.scenario.samplers import LatinHypercubeSampler
from roboprobe.selection.base import FloatArray, Strategy, StrategyContext

__all__ = ["LHSStrategy"]


class LHSStrategy(Strategy):
    """Centred-discrepancy Latin hypercube, generated once per campaign."""

    id: ClassVar[str] = "S-LHS"

    def __init__(self, ctx: StrategyContext) -> None:
        """Start at the beginning of the campaign design."""
        super().__init__(ctx)
        self._index = 0
        self._design: FloatArray | None = None

    def _design_points(self) -> FloatArray:
        if self._design is None:
            rng = make_rng(self.ctx.seed, STRATEGY)
            self._design = LatinHypercubeSampler(self.ctx.space.dim).sample(self.ctx.budget, rng)
        return self._design

    def is_exhausted(self) -> bool:
        """True after the B-point design has been consumed."""
        return self._index >= self.ctx.budget

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
        """Index into the regenerated design."""
        return {"index": self._index}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        """Restore consume index; the design is rebuilt from the campaign seed."""
        self._index = int(state.get("index", 0))
        self._design = None
