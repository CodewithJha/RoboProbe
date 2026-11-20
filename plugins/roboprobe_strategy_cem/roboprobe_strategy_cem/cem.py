"""S-CEM: truncated-Gaussian mixture cross-entropy sampler (docs/07 §8).

Implements: FR-SEL-009, PR-21
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from roboprobe.core.settings.selection import CemDefaults
from roboprobe.core.types import Observation, Phase, Verdict
from roboprobe.selection.base import FloatArray, Strategy, StrategyContext, StrategyParams

__all__ = ["CEMParams", "CEMStrategy"]


class CEMParams(StrategyParams):
    """Campaign overrides for S-CEM."""

    model_config = ConfigDict(extra="ignore")

    round_size: int | None = Field(default=None, gt=0)
    elite_fraction: float | None = Field(default=None, gt=0, le=1)
    n_components: int | None = Field(default=None, ge=1)
    min_std: float | None = Field(default=None, gt=0, le=1)


class CEMStrategy(Strategy):
    """Cross-entropy rare-event baseline as an external-style plugin."""

    id: ClassVar[str] = "S-CEM"
    phase: ClassVar[Phase] = "baseline"
    Params: ClassVar[type[BaseModel]] = CEMParams

    def __init__(self, ctx: StrategyContext) -> None:
        """Initialise a uniform mixture over the unit cube."""
        super().__init__(ctx)
        self.params: CEMParams
        defaults = CemDefaults()
        self._round_size = int(
            defaults.round_size if self.params.round_size is None else self.params.round_size
        )
        self._elite_fraction = float(
            defaults.elite_fraction
            if self.params.elite_fraction is None
            else self.params.elite_fraction
        )
        self._n_components = int(
            defaults.n_components if self.params.n_components is None else self.params.n_components
        )
        self._min_std = float(
            defaults.min_std if self.params.min_std is None else self.params.min_std
        )
        dim = ctx.space.dim
        self._means = np.full((self._n_components, dim), 0.5, dtype=np.float64)
        self._stds = np.full((self._n_components, dim), 0.25, dtype=np.float64)
        self._weights = np.full(self._n_components, 1.0 / self._n_components, dtype=np.float64)
        self._since_update = 0
        self._last_fit_n = 0

    def _propose_impl(
        self,
        history: Sequence[Observation],
        pending: Sequence[FloatArray],
        q: int,
        rng: np.random.Generator,
    ) -> list[FloatArray]:
        del pending
        self._maybe_update(history)
        if q <= 0:
            return []
        return [self._sample_one(rng) for _ in range(q)]

    def state_dict(self) -> dict[str, Any]:
        """Checkpoint mixture parameters and update counters."""
        return {
            "means": self._means.tolist(),
            "stds": self._stds.tolist(),
            "weights": self._weights.tolist(),
            "since_update": self._since_update,
            "last_fit_n": self._last_fit_n,
            "round_size": self._round_size,
            "elite_fraction": self._elite_fraction,
            "n_components": self._n_components,
            "min_std": self._min_std,
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        """Restore :meth:`state_dict` output."""
        self._means = np.asarray(state["means"], dtype=np.float64)
        self._stds = np.asarray(state["stds"], dtype=np.float64)
        self._weights = np.asarray(state["weights"], dtype=np.float64)
        self._since_update = int(state["since_update"])
        self._last_fit_n = int(state["last_fit_n"])
        self._round_size = int(state["round_size"])
        self._elite_fraction = float(state["elite_fraction"])
        self._n_components = int(state["n_components"])
        self._min_std = float(state["min_std"])

    def _maybe_update(self, history: Sequence[Observation]) -> None:
        valid = [obs for obs in history if obs.verdict is not Verdict.INVALID]
        if len(valid) - self._last_fit_n < self._round_size:
            return
        window = valid[-self._round_size :]
        x = np.stack([np.asarray(obs.x_unit, dtype=np.float64) for obs in window])
        y = np.asarray([float(obs.robustness or 0.0) for obs in window], dtype=np.float64)
        n_elite = max(1, int(np.ceil(self._elite_fraction * len(window))))
        elite = x[np.argsort(y)[:n_elite]]
        # Soft assignment to components by nearest mean; refit truncated-Gaussian params.
        if self._n_components == 1:
            self._means[0] = elite.mean(axis=0)
            self._stds[0] = np.maximum(elite.std(axis=0), self._min_std)
            self._weights[:] = 1.0
        else:
            labels = np.argmin(
                np.sum((elite[:, None, :] - self._means[None, :, :]) ** 2, axis=-1),
                axis=1,
            )
            for k in range(self._n_components):
                members = elite[labels == k]
                if members.shape[0] == 0:
                    continue
                self._means[k] = members.mean(axis=0)
                self._stds[k] = np.maximum(members.std(axis=0), self._min_std)
                self._weights[k] = members.shape[0] / elite.shape[0]
            total = float(self._weights.sum())
            if total > 0.0:
                self._weights /= total
        self._last_fit_n = len(valid)
        self._since_update = 0

    def _sample_one(self, rng: np.random.Generator) -> FloatArray:
        component = int(rng.choice(self._n_components, p=self._weights))
        raw = rng.normal(self._means[component], self._stds[component])
        return np.clip(raw, 0.0, 1.0)
