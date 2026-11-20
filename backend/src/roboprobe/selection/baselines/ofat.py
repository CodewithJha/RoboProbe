"""S-OFAT: one-factor-at-a-time sweeps from nominal (docs/07 §3).

Implements: FR-SEL-001, PR-04
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

import numpy as np

from roboprobe.core.settings.selection import SelectionDefaults
from roboprobe.core.types import Observation
from roboprobe.selection.base import FloatArray, Strategy, StrategyContext

__all__ = ["OFATStrategy"]


class OFATStrategy(Strategy):
    """Nominal point with one free parameter moved to each configured level.

    After ``d · |L|`` unique scenarios the design cycles (noise repeats); ``allow_repeats``
    is enabled for the wrap so the base class accepts the duplicates.
    """

    id: ClassVar[str] = "S-OFAT"

    def __init__(self, ctx: StrategyContext) -> None:
        """Start at the first (parameter, level) pair."""
        super().__init__(ctx)
        self._index = 0
        self._design: FloatArray | None = None

    def _design_points(self) -> FloatArray:
        if self._design is None:
            levels = np.asarray(SelectionDefaults().ofat.levels, dtype=np.float64)
            nominal = self.ctx.space.to_unit(self.ctx.space.nominal_values())
            rows: list[FloatArray] = []
            for axis in range(self.ctx.space.dim):
                for level in levels:
                    point = nominal.copy()
                    point[axis] = float(level)
                    rows.append(point)
            self._design = np.stack(rows, axis=0)
        return self._design

    def _propose_impl(
        self,
        history: Sequence[Observation],
        pending: Sequence[FloatArray],
        q: int,
        rng: np.random.Generator,
    ) -> list[FloatArray]:
        del history, pending, rng
        design = self._design_points()
        n = design.shape[0]
        out: list[FloatArray] = []
        for _ in range(q):
            if self._index >= n:
                self._allow_repeats = True
            out.append(design[self._index % n].copy())
            self._index += 1
        return out

    def state_dict(self) -> dict[str, Any]:
        """Consume index into the cycling OFAT design."""
        return {"index": self._index, "allow_repeats": self._allow_repeats}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        """Restore consume index and wrap flag."""
        self._index = int(state.get("index", 0))
        self._allow_repeats = bool(state.get("allow_repeats", False))
        self._design = None
