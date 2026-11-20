"""S-RANDOM: i.i.d. draws mapped through each parameter's prior (docs/07 §3).

Implements: FR-SEL-001, PR-04
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

import numpy as np

from roboprobe.core.types import Observation
from roboprobe.scenario.samplers import PriorSampler
from roboprobe.selection.base import FloatArray, Strategy, StrategyContext

__all__ = ["RandomStrategy"]


class RandomStrategy(Strategy):
    """Uniform / prior random baseline."""

    id: ClassVar[str] = "S-RANDOM"

    def __init__(self, ctx: StrategyContext) -> None:
        """Bind ``PriorSampler`` to the free parameters."""
        super().__init__(ctx)
        self._n_draws = 0
        self._sampler = PriorSampler(self.ctx.space.params)

    def _propose_impl(
        self,
        history: Sequence[Observation],
        pending: Sequence[FloatArray],
        q: int,
        rng: np.random.Generator,
    ) -> list[FloatArray]:
        del history, pending
        if q == 0:
            return []
        batch = self._sampler.sample(q, rng)
        self._n_draws += q
        return [batch[i].copy() for i in range(batch.shape[0])]

    def state_dict(self) -> dict[str, Any]:
        """Number of prior draws so far."""
        return {"n_draws": self._n_draws}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        """Restore draw count."""
        self._n_draws = int(state.get("n_draws", 0))
