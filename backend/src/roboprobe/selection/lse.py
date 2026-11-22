"""S-LSE: Sobol warm-up then straddle level-set batches (docs/07 §7).

Implements: FR-SEL-004, PR-15
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

import numpy as np
import numpy.typing as npt
import structlog
from pydantic import BaseModel, ConfigDict, Field

from roboprobe.core import errors
from roboprobe.core.errors import ModelFitError
from roboprobe.core.seeding import STRATEGY, derive_seed
from roboprobe.core.types import Observation, Phase, Proposal, Verdict
from roboprobe.selection._compat import AcquisitionFunction, torch
from roboprobe.selection.acquisition import Straddle
from roboprobe.selection.base import FloatArray, Strategy, StrategyContext, StrategyParams
from roboprobe.selection.optimize import kriging_believer_batch
from roboprobe.selection.surrogate import RobustnessGP
from roboprobe.selection.warmup import WarmupState, warmup_size

__all__ = ["LevelSetParams", "LevelSetStrategy"]

log = structlog.get_logger(__name__)


class LevelSetParams(StrategyParams):
    """Campaign overrides for S-LSE."""

    model_config = ConfigDict(extra="ignore")

    n0_fraction: float | None = Field(default=None, gt=0, le=1)
    n0_min_factor: int | None = Field(default=None, ge=1)
    beta_straddle: float | None = Field(default=None, gt=0)


class LevelSetStrategy(Strategy):
    """Boundary-focused ablation using the straddle acquisition."""

    id: ClassVar[str] = "S-LSE"
    phase: ClassVar[Phase] = "boundary"
    Params: ClassVar[type[BaseModel]] = LevelSetParams

    def __init__(self, ctx: StrategyContext) -> None:
        """Bind warm-up cursor and straddle beta."""
        super().__init__(ctx)
        self.params: LevelSetParams
        probe = ctx.selection.probe
        self._n0 = warmup_size(
            ctx.budget,
            ctx.space.dim,
            n0_fraction=self.params.n0_fraction,
            n0_min_factor=self.params.n0_min_factor,
        )
        self._beta = float(
            probe.beta_straddle if self.params.beta_straddle is None else self.params.beta_straddle
        )
        self._warmup = WarmupState(ctx.space.dim, ctx.seed)
        self._gp_settings = ctx.selection.gp
        self._acq_settings = ctx.selection.acq
        self._meta: list[dict[str, Any]] = []

    def propose(
        self,
        history: Sequence[Observation],
        pending: Sequence[npt.NDArray[np.floating[Any]]],
        q: int,
    ) -> list[Proposal]:
        """Warm-up Sobol, then straddle batches with Kriging Believer."""
        if q < 0:
            msg = f"propose q must be >= 0, got {q}"
            raise errors.ValidationError(msg, context={"q": q})
        if q == 0:
            return []
        valid = tuple(obs for obs in history if obs.verdict is not Verdict.INVALID)
        rng = np.random.default_rng(derive_seed(self.ctx.seed, STRATEGY, len(valid)))
        pending_unit = [np.asarray(p, dtype=np.float64).reshape(-1) for p in pending]
        history_unit = [np.asarray(obs.x_unit, dtype=np.float64) for obs in valid]
        try:
            raw = self._propose_raw(valid, pending_unit, q, rng)
        except ModelFitError:
            log.info("selector.fallback", strategy=self.id, reason="ModelFitError")
            raw = self._warmup.sample(q, rng)
            fallback = {"phase": "explore", "mean": None, "std": None, "tags": ("fallback",)}
            self._meta = [fallback for _ in raw]
        accepted: list[FloatArray] = []
        metas: list[dict[str, Any]] = []
        for point, meta in zip(raw, self._meta, strict=True):
            candidate = np.clip(point, 0.0, 1.0)
            if not self._feasible(candidate):
                continue
            if self._is_duplicate(
                candidate, history_unit, pending_unit, accepted, self._allow_repeats
            ):
                continue
            accepted.append(candidate)
            metas.append(meta)
            if len(accepted) == q:
                break
        if not accepted:
            msg = f"{self.id} could not propose a feasible unique point"
            raise errors.StrategyError(msg, context={"strategy": self.id, "q": q})
        out: list[Proposal] = []
        for point, meta in zip(accepted, metas, strict=True):
            scenario = self.ctx.space.make_scenario(self.ctx.space.from_unit(point))
            out.append(
                Proposal(
                    scenario=scenario,
                    strategy=self.id,
                    phase=meta["phase"],
                    predicted_mean=meta["mean"],
                    predicted_std=meta["std"],
                    tags=tuple(meta.get("tags", ())),
                )
            )
        return out

    def state_dict(self) -> dict[str, Any]:
        """Checkpoint Sobol warm-up cursor."""
        return {"warmup": self._warmup.state_dict()}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        """Restore warm-up cursor."""
        self._warmup.load_state_dict(state["warmup"])

    def _propose_impl(
        self,
        history: Sequence[Observation],
        pending: Sequence[FloatArray],
        q: int,
        rng: np.random.Generator,
    ) -> list[FloatArray]:
        del history, pending, q, rng
        return []

    def _propose_raw(
        self,
        history: Sequence[Observation],
        pending: Sequence[FloatArray],
        q: int,
        rng: np.random.Generator,
    ) -> list[FloatArray]:
        self._meta = []
        if len(history) < self._n0:
            points = self._warmup.sample(q, rng)
            warm = {"phase": "warmup", "mean": None, "std": None, "tags": ()}
            self._meta = [warm for _ in points]
            return points
        x = np.stack([np.asarray(obs.x_unit, dtype=np.float64) for obs in history])
        y = np.asarray([float(obs.robustness or 0.0) for obs in history], dtype=np.float64)
        gp = RobustnessGP(self.ctx.space.dim, seed=self.ctx.seed, gp=self._gp_settings)
        gp.fit(x, y)
        floor = self._gp_settings.noise_lower_bound
        beta = self._beta

        def factory(model: RobustnessGP) -> AcquisitionFunction:
            return Straddle(model.botorch_model(), beta=beta, noise_floor=floor)

        gen = torch.Generator().manual_seed(derive_seed(self.ctx.seed, STRATEGY, x.shape[0]))
        points = kriging_believer_batch(
            gp,
            factory,
            q,
            settings=self._acq_settings,
            generator=gen,
            is_feasible=self._feasible,
            existing=list(pending),
        )
        for point in points:
            mean, std = gp.predict(point.reshape(1, -1))
            self._meta.append(
                {"phase": "boundary", "mean": float(mean[0]), "std": float(std[0]), "tags": ()}
            )
        return points
