"""S-SOBOL: scrambled Sobol' sequence consumed in order (docs/07 §3).

Implements: FR-SEL-001, PR-04
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

import numpy as np

from roboprobe.core.seeding import STRATEGY, derive_seed
from roboprobe.core.types import Observation
from roboprobe.scenario.samplers import SobolSampler
from roboprobe.selection.base import FloatArray, Strategy, StrategyContext

__all__ = ["SobolStrategy"]


class SobolStrategy(Strategy):
    """Scrambled Sobol' baseline; prefixes of size ``2^m`` are balanced."""

    id: ClassVar[str] = "S-SOBOL"

    def __init__(self, ctx: StrategyContext) -> None:
        """Start at position 0 of the scrambled sequence."""
        super().__init__(ctx)
        self._index = 0
        self._sampler: SobolSampler | None = None

    def _engine(self) -> SobolSampler:
        if self._sampler is None:
            seed = derive_seed(self.ctx.seed, STRATEGY)
            self._sampler = SobolSampler(self.ctx.space.dim, seed=seed)
            if self._index:
                self._sampler.fast_forward(self._index)
        return self._sampler

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
        batch = self._engine().sample(q, rng)
        self._index += q
        return [batch[i].copy() for i in range(batch.shape[0])]

    def state_dict(self) -> dict[str, Any]:
        """Consume position in the Sobol' sequence."""
        return {"index": self._index}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        """Restore position; the engine is rebuilt on the next draw."""
        self._index = int(state.get("index", 0))
        self._sampler = None
