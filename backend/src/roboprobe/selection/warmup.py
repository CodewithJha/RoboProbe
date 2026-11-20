"""Shared Sobol warm-up sizing and sampling for S-BO / S-LSE / S-PROBE (docs/07 §6.3).

Implements: FR-SEL-002, FR-SEL-003
"""

from __future__ import annotations

import math

import numpy as np

from roboprobe.core.seeding import STRATEGY, derive_seed
from roboprobe.core.settings.selection import ProbeDefaults
from roboprobe.scenario.samplers import SobolSampler
from roboprobe.selection.base import FloatArray

__all__ = ["WarmupState", "warmup_size"]


def warmup_size(
    budget: int,
    dim: int,
    *,
    n0_fraction: float | None = None,
    n0_min_factor: int | None = None,
) -> int:
    """``n0 = max(n0_min_factor * d, ceil(n0_fraction * B))`` (docs/07 §6.3).

    Args:
        budget: Campaign evaluation budget ``B``.
        dim: Scenario-space dimension ``d``.
        n0_fraction: Override of ``selection.probe.n0_fraction``.
        n0_min_factor: Override of ``selection.probe.n0_min_factor``.

    Returns:
        Warm-up length (at least 1).
    """
    defaults = ProbeDefaults()
    fraction = defaults.n0_fraction if n0_fraction is None else n0_fraction
    factor = defaults.n0_min_factor if n0_min_factor is None else n0_min_factor
    return max(factor * dim, math.ceil(fraction * budget), 1)


class WarmupState:
    """Scrambled Sobol cursor shared by warm-up and Explore phases."""

    def __init__(self, dim: int, seed: int, *, index: int = 0) -> None:
        """Bind dimension and root seed; ``index`` is the consume position."""
        self.dim = dim
        self.seed = seed
        self.index = index
        self._sampler: SobolSampler | None = None

    def _engine(self) -> SobolSampler:
        if self._sampler is None:
            self._sampler = SobolSampler(self.dim, seed=derive_seed(self.seed, STRATEGY))
            if self.index:
                self._sampler.fast_forward(self.index)
        return self._sampler

    def sample(self, q: int, rng: np.random.Generator) -> list[FloatArray]:
        """Draw the next ``q`` Sobol points and advance the cursor."""
        if q <= 0:
            return []
        batch = self._engine().sample(q, rng)
        self.index += q
        return [np.asarray(batch[i], dtype=np.float64).copy() for i in range(batch.shape[0])]

    def state_dict(self) -> dict[str, int]:
        """JSON-serialisable consume position."""
        return {"index": self.index}

    def load_state_dict(self, state: dict[str, int]) -> None:
        """Restore consume position; the engine rebuilds lazily."""
        self.index = int(state.get("index", 0))
        self._sampler = None
