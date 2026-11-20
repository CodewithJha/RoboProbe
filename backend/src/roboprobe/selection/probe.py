"""S-PROBE phased hybrid strategy (docs/07 §6).

Implements: FR-SEL-003, FR-SEL-008, PR-03
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
from roboprobe.core.settings.selection import (
    AcquisitionDefaults,
    GpDefaults,
    ProbeDefaults,
    ProbeWeights,
    SelectionDefaults,
)
from roboprobe.core.types import Observation, Phase, Proposal, Verdict
from roboprobe.selection._compat import AcquisitionFunction, torch
from roboprobe.selection.acquisition import Straddle, make_qlognei
from roboprobe.selection.base import FloatArray, Strategy, StrategyContext, StrategyParams
from roboprobe.selection.diversity import DiversityPenalizedEV, ModeCache
from roboprobe.selection.optimize import kriging_believer_batch, optimize
from roboprobe.selection.probe_phases import PhaseController, PhaseView
from roboprobe.selection.refine import RefineScheduler
from roboprobe.selection.surrogate import RobustnessGP
from roboprobe.selection.warmup import WarmupState, warmup_size

__all__ = ["ProbeParams", "ProbeStrategy"]

log = structlog.get_logger(__name__)


class ProbeParams(StrategyParams):
    """Campaign overrides for S-PROBE (docs/07 §6.3)."""

    model_config = ConfigDict(extra="ignore")

    n0_fraction: float | None = Field(default=None, gt=0, le=1)
    n0_min_factor: int | None = Field(default=None, ge=1)
    epsilon: float | None = Field(default=None, ge=0, le=1)
    lambda_div: float | None = Field(default=None, ge=0)
    kappa_radius: float | None = Field(default=None, gt=0)
    beta_straddle: float | None = Field(default=None, gt=0)
    adapt_window: int | None = Field(default=None, gt=0)
    adapt_shift: float | None = Field(default=None, gt=0, le=1)
    mode_search_floor: float | None = Field(default=None, ge=0, le=1)
    refine_bisect_steps: int | None = Field(default=None, ge=0)
    refine_perturb_n: int | None = Field(default=None, ge=0)
    refine_perturb_std: float | None = Field(default=None, gt=0)
    weights: ProbeWeights | None = None


class ProbeStrategy(Strategy):
    """Default intelligent selector: warm-up → falsify → mixed phases."""

    id: ClassVar[str] = "S-PROBE"
    phase: ClassVar[Phase] = "warmup"
    Params: ClassVar[type[BaseModel]] = ProbeParams

    def __init__(self, ctx: StrategyContext) -> None:
        """Wire GP, phase controller, refine queue and Sobol warm-up."""
        super().__init__(ctx)
        self.params: ProbeParams
        probe = ProbeDefaults()
        selection = SelectionDefaults()
        self._gp_settings = GpDefaults()
        self._acq_settings = AcquisitionDefaults()
        self._n0 = warmup_size(
            ctx.budget,
            ctx.space.dim,
            n0_fraction=self.params.n0_fraction,
            n0_min_factor=self.params.n0_min_factor,
        )
        self._lambda_div = float(
            probe.lambda_div if self.params.lambda_div is None else self.params.lambda_div
        )
        self._kappa = float(
            probe.kappa_radius if self.params.kappa_radius is None else self.params.kappa_radius
        )
        self._beta = float(
            probe.beta_straddle if self.params.beta_straddle is None else self.params.beta_straddle
        )
        self._warmup = WarmupState(ctx.space.dim, ctx.seed)
        self._phases = PhaseController(
            n0=self._n0,
            weights=self.params.weights if self.params.weights is not None else probe.weights,
            epsilon=self.params.epsilon,
            adapt_window=self.params.adapt_window,
            adapt_shift=self.params.adapt_shift,
            mode_search_floor=self.params.mode_search_floor,
        )
        self._refine = RefineScheduler(
            nominal=ctx.space.to_unit(ctx.space.nominal_values()),
            bisect_steps=self.params.refine_bisect_steps,
            perturb_n=self.params.refine_perturb_n,
            perturb_std=self.params.refine_perturb_std,
            seed=derive_seed(ctx.seed, STRATEGY),
        )
        self._modes = ModeCache(refresh_every=selection.mode_cache_refresh_every)
        self._known_mode_keys: set[str] = set()
        self._meta: list[dict[str, Any]] = []
        self._pending_mode_search: list[FloatArray] = []

    def propose(
        self,
        history: Sequence[Observation],
        pending: Sequence[npt.NDArray[np.floating[Any]]],
        q: int,
    ) -> list[Proposal]:
        """Propose with per-slot phases and rationale (docs/07 §6.2)."""
        if q < 0:
            msg = f"propose q must be >= 0, got {q}"
            raise errors.ValidationError(msg, context={"q": q})
        if q == 0:
            return []
        valid = tuple(obs for obs in history if obs.verdict is not Verdict.INVALID)
        self._refine.ingest(valid)
        self._sync_modes(valid)
        rng = np.random.default_rng(derive_seed(self.ctx.seed, STRATEGY, len(valid)))
        pending_unit = [np.asarray(p, dtype=np.float64).reshape(-1) for p in pending]
        history_unit = [np.asarray(obs.x_unit, dtype=np.float64) for obs in valid]
        try:
            raw = self._propose_raw(valid, pending_unit, q, rng)
        except ModelFitError:
            log.info("selector.fallback", strategy=self.id, reason="ModelFitError")
            raw = self._warmup.sample(q, rng)
            self._meta = [_meta("explore", tags=("fallback",)) for _ in raw]
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
        return [
            _to_proposal(self, point, meta) for point, meta in zip(accepted, metas, strict=True)
        ]

    def observe(self, obs: Observation) -> None:
        """Record ModeSearch productivity once the observation returns."""
        if obs.verdict is Verdict.INVALID:
            return
        x = np.asarray(obs.x_unit, dtype=np.float64)
        remaining: list[FloatArray] = []
        matched = False
        for pending in self._pending_mode_search:
            if float(np.max(np.abs(pending - x))) <= self._history_tol:
                matched = True
            else:
                remaining.append(pending)
        self._pending_mode_search = remaining
        if not matched:
            return
        new_mode = False
        if obs.verdict is Verdict.FAIL:
            if self._modes.medoids.size == 0:
                new_mode = True
            else:
                delta = self._modes.medoids - x.reshape(1, -1)
                new_mode = bool(np.min(np.max(np.abs(delta), axis=1)) > self._kappa)
        self._phases.record_outcome("mode_search", new_mode)

    def state_dict(self) -> dict[str, Any]:
        """Checkpoint Sobol, phases, refine and mode-search pending."""
        return {
            "warmup": self._warmup.state_dict(),
            "phases": self._phases.state_dict(),
            "refine": self._refine.state_dict(),
            "known_mode_keys": sorted(self._known_mode_keys),
            "pending_mode_search": [p.tolist() for p in self._pending_mode_search],
            "medoids": self._modes.medoids.tolist(),
            "mode_last_n": self._modes._last_n,
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        """Restore :meth:`state_dict` output."""
        self._warmup.load_state_dict(state["warmup"])
        self._phases.load_state_dict(state["phases"])
        self._refine.load_state_dict(state["refine"])
        self._known_mode_keys = set(state.get("known_mode_keys", []))
        self._pending_mode_search = [
            np.asarray(p, dtype=np.float64) for p in state.get("pending_mode_search", [])
        ]
        medoids = np.asarray(state.get("medoids", []), dtype=np.float64)
        if medoids.size:
            self._modes.medoids = medoids
        self._modes._last_n = state.get("mode_last_n")

    def _propose_impl(
        self,
        history: Sequence[Observation],
        pending: Sequence[FloatArray],
        q: int,
        rng: np.random.Generator,
    ) -> list[FloatArray]:
        """Unused; :meth:`propose` owns the path."""
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
            self._meta = [_meta("warmup") for _ in points]
            return points
        x = np.stack([np.asarray(obs.x_unit, dtype=np.float64) for obs in history])
        y = np.asarray([float(obs.robustness or 0.0) for obs in history], dtype=np.float64)
        gp = RobustnessGP(self.ctx.space.dim, seed=self.ctx.seed, gp=self._gp_settings)
        gp.fit(x, y)
        if not bool(np.any(y < 0.0)):
            return self._falsify_batch(gp, x, pending, q)
        return self._mixed_batch(gp, history, pending, q, rng)

    def _falsify_batch(
        self,
        gp: RobustnessGP,
        x_obs: npt.NDArray[np.float64],
        pending: Sequence[FloatArray],
        q: int,
    ) -> list[FloatArray]:
        baseline = torch.as_tensor(x_obs, dtype=torch.float64)
        pending_t = (
            torch.as_tensor(np.stack(list(pending)), dtype=torch.float64) if pending else None
        )

        def factory(model: RobustnessGP) -> AcquisitionFunction:
            return make_qlognei(model.botorch_model(), baseline, x_pending=pending_t)

        gen = torch.Generator().manual_seed(derive_seed(self.ctx.seed, STRATEGY, x_obs.shape[0]))
        points = kriging_believer_batch(
            gp,
            factory,
            q,
            settings=self._acq_settings,
            generator=gen,
            is_feasible=self._feasible,
            existing=list(pending),
        )
        self._meta = []
        for point in points:
            mean, std = gp.predict(point.reshape(1, -1))
            self._meta.append(_meta("falsify", mean=float(mean[0]), std=float(std[0])))
        return points

    def _mixed_batch(
        self,
        gp: RobustnessGP,
        history: Sequence[Observation],
        pending: Sequence[FloatArray],
        q: int,
        rng: np.random.Generator,
    ) -> list[FloatArray]:
        out: list[FloatArray] = []
        known = [np.asarray(p, dtype=np.float64).reshape(-1) for p in pending]
        model = gp
        for _ in range(q):
            phase = self._phases.choose_phase(
                rng,
                PhaseView(len(history), True, self._refine.refine_available),
            )
            point, meta = self._point_for_phase(phase, model, history, known, rng)
            out.append(point)
            known.append(point)
            self._meta.append(meta)
            if phase == "mode_search":
                self._pending_mode_search.append(point.copy())
            mean, _ = model.predict(point.reshape(1, -1))
            model = model.condition_on_observations(point, mean)
        return out

    def _point_for_phase(
        self,
        phase: Phase,
        gp: RobustnessGP,
        history: Sequence[Observation],
        existing: Sequence[FloatArray],
        rng: np.random.Generator,
    ) -> tuple[FloatArray, dict[str, Any]]:
        if phase in {"warmup", "explore"}:
            return self._warmup.sample(1, rng)[0], _meta(phase)
        if phase == "refine":
            point = self._refine.next_point(history)
            if point is None:
                return self._warmup.sample(1, rng)[0], _meta("explore")
            mean, std = gp.predict(point.reshape(1, -1))
            return point, _meta("refine", mean=float(mean[0]), std=float(std[0]))
        gen = torch.Generator().manual_seed(int(rng.integers(0, 2**31 - 1)))
        acq: AcquisitionFunction
        if phase == "boundary":
            acq = Straddle(
                gp.botorch_model(),
                beta=self._beta,
                noise_floor=self._gp_settings.noise_lower_bound,
            )
        else:
            acq = DiversityPenalizedEV(
                gp.botorch_model(),
                medoids=self._modes.medoids,
                lengthscales=gp.lengthscales,
                lambda_div=self._lambda_div,
                kappa_radius=self._kappa,
                noise_floor=self._gp_settings.noise_lower_bound,
            )
        point = optimize(
            acq,
            d=self.ctx.space.dim,
            settings=self._acq_settings,
            generator=gen,
            is_feasible=self._feasible,
            existing=existing,
        )
        mean, std = gp.predict(point.reshape(1, -1))
        raw = acq.forward(torch.as_tensor(point, dtype=torch.float64).view(1, 1, -1))
        value = float(raw.detach()[0])
        return point, _meta(phase, acq=value, mean=float(mean[0]), std=float(std[0]))

    def _sync_modes(self, history: Sequence[Observation]) -> None:
        fails = [
            np.asarray(obs.x_unit, dtype=np.float64)
            for obs in history
            if obs.verdict is Verdict.FAIL
        ]
        if not fails:
            return
        medoids = self._modes.update(np.stack(fails), n_obs=len(history))
        for medoid in medoids:
            key = ",".join(f"{float(v):.6f}" for v in medoid.reshape(-1))
            if key in self._known_mode_keys:
                continue
            self._known_mode_keys.add(key)
            self._refine.add_mode(medoid, mode_key=key)


def _meta(
    phase: Phase,
    *,
    acq: float | None = None,
    mean: float | None = None,
    std: float | None = None,
    tags: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "phase": phase,
        "acquisition_value": acq,
        "predicted_mean": mean,
        "predicted_std": std,
        "tags": tags,
    }


def _to_proposal(strategy: ProbeStrategy, point: FloatArray, meta: dict[str, Any]) -> Proposal:
    scenario = strategy.ctx.space.make_scenario(strategy.ctx.space.from_unit(point))
    return Proposal(
        scenario=scenario,
        strategy=strategy.id,
        phase=meta["phase"],
        acquisition_value=meta["acquisition_value"],
        predicted_mean=meta["predicted_mean"],
        predicted_std=meta["predicted_std"],
        tags=tuple(meta.get("tags", ())),
    )
