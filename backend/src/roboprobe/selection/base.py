"""Strategy ABC: template-method ``propose`` enforces the selection contract (docs/05 §4).

Implements: FR-SEL-005, FR-SEL-006, FR-SEL-007, PR-19
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, ClassVar, Final

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field

from roboprobe.core import errors
from roboprobe.core.seeding import STRATEGY, make_rng
from roboprobe.core.settings.scenario import ScenarioSettings
from roboprobe.core.settings.selection import SelectionDefaults
from roboprobe.core.types import Observation, Phase, Proposal, Verdict
from roboprobe.scenario.space import ScenarioSpace

__all__ = [
    "HISTORY_LINF_TOL",
    "PLUGIN_API_VERSION",
    "Strategy",
    "StrategyContext",
    "StrategyParams",
]

PLUGIN_API_VERSION: Final = 1
"""Plugin API version every strategy class must declare (docs/05, ADR-0016)."""

HISTORY_LINF_TOL: Final = 1e-6
"""Normalised L∞ gap vs history/pending required by the strategy contract (docs/05 §4)."""

FloatArray = npt.NDArray[np.float64]


class StrategyContext(BaseModel):
    """Inputs shared by every strategy for one campaign (docs/05 §4)."""

    model_config = ConfigDict(frozen=True)

    space: ScenarioSpace
    budget: int = Field(gt=0)
    seed: int = Field(ge=0)
    batch_size: int = Field(gt=0)
    params: dict[str, Any] = Field(default_factory=dict)
    selection: SelectionDefaults = Field(default_factory=SelectionDefaults)
    scenario: ScenarioSettings = Field(default_factory=ScenarioSettings)


class StrategyParams(BaseModel):
    """Optional per-strategy knobs from ``StrategyContext.params`` (docs/07 §10)."""

    model_config = ConfigDict(extra="ignore")

    allow_repeats: bool = False
    max_attempts: int | None = Field(default=None, gt=0)
    dedupe_tol: float | None = Field(default=None, gt=0)


class Strategy(ABC):
    """Template method around :meth:`_propose_impl` (docs/34 §4).

    Subclasses draw candidates; this class clips, checks feasibility, de-duplicates, drops
    ``INVALID`` history, and wraps :class:`Proposal` values.
    """

    id: ClassVar[str]
    PLUGIN_API_VERSION: ClassVar[int] = PLUGIN_API_VERSION
    phase: ClassVar[Phase] = "baseline"
    Params: ClassVar[type[BaseModel]] = StrategyParams

    def __init__(self, ctx: StrategyContext) -> None:
        """Validate ``ctx.params`` against :attr:`Params`.

        Args:
            ctx: Campaign strategy context.
        """
        self.ctx = ctx
        self.params = self.Params.model_validate(ctx.params)
        selection = ctx.selection
        scenario = ctx.scenario
        configured = self.params if isinstance(self.params, StrategyParams) else StrategyParams()
        self._allow_repeats = bool(getattr(self.params, "allow_repeats", configured.allow_repeats))
        override_attempts = getattr(self.params, "max_attempts", None)
        self._max_attempts = (
            int(override_attempts) if override_attempts else scenario.constraint_max_attempts
        )
        override_tol = getattr(self.params, "dedupe_tol", None)
        self._batch_tol = float(override_tol) if override_tol else selection.acq.dedupe_tol
        self._history_tol = HISTORY_LINF_TOL

    def propose(
        self,
        history: Sequence[Observation],
        pending: Sequence[npt.NDArray[np.floating[Any]]],
        q: int,
    ) -> list[Proposal]:
        """Return ``q`` feasible, de-duplicated proposals (or fewer if exhausted).

        Args:
            history: Finished observations; ``INVALID`` rows are ignored.
            pending: Unit-cube points already in flight.
            q: Number of proposals requested.

        Returns:
            Proposals inside the pinned space.

        Raises:
            roboprobe.core.errors.StrategyError: If no feasible unique point is found in time.
            roboprobe.core.errors.ValidationError: If ``q`` is negative.
        """
        if q < 0:
            msg = f"propose q must be >= 0, got {q}"
            raise errors.ValidationError(msg, context={"q": q})
        if q == 0 or self.is_exhausted():
            return []
        valid = tuple(obs for obs in history if obs.verdict is not Verdict.INVALID)
        rng = make_rng(self.ctx.seed, STRATEGY, len(valid))
        pending_unit = [_as_unit(p, self.ctx.space.dim) for p in pending]
        history_unit = [_as_unit(obs.x_unit, self.ctx.space.dim) for obs in valid]
        accepted: list[FloatArray] = []
        attempts = 0
        while len(accepted) < q and attempts < self._max_attempts:
            if self.is_exhausted():
                break
            attempts += 1
            need = q - len(accepted)
            raw = self._propose_impl(valid, pending_unit + accepted, need, rng)
            if not raw:
                break
            for point in raw:
                candidate = np.clip(_as_unit(point, self.ctx.space.dim), 0.0, 1.0)
                if not self._feasible(candidate):
                    continue
                if self._is_duplicate(
                    candidate, history_unit, pending_unit, accepted, self._allow_repeats
                ):
                    continue
                accepted.append(candidate)
                if len(accepted) == q:
                    break
        if not accepted and q > 0 and not self.is_exhausted():
            msg = f"{self.id} could not propose a feasible unique point"
            raise errors.StrategyError(msg, context={"strategy": self.id, "q": q})
        return [self._to_proposal(point) for point in accepted]

    def observe(self, obs: Observation) -> None:
        """Optional incremental update; default is a no-op.

        Args:
            obs: Newly finished observation.
        """
        del obs

    def state_dict(self) -> dict[str, Any]:
        """JSON-serialisable checkpoint (docs/05 §4)."""
        return {}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        """Restore :meth:`state_dict` output.

        Args:
            state: Previously returned checkpoint.
        """
        del state

    def is_exhausted(self) -> bool:
        """Whether a finite design has been fully consumed (GRID/OFAT)."""
        return False

    @abstractmethod
    def _propose_impl(
        self,
        history: Sequence[Observation],
        pending: Sequence[FloatArray],
        q: int,
        rng: np.random.Generator,
    ) -> list[FloatArray]:
        """Draw ``q`` raw unit-cube candidates; ``propose`` clips, checks and de-duplicates."""

    def _feasible(self, unit: FloatArray) -> bool:
        values = {**self.ctx.space.nominal_values(), **self.ctx.space.from_unit(unit)}
        return self.ctx.space.is_feasible(values)

    def _is_duplicate(
        self,
        candidate: FloatArray,
        history: Sequence[FloatArray],
        pending: Sequence[FloatArray],
        batch: Sequence[FloatArray],
        allow_repeats: bool,
    ) -> bool:
        if allow_repeats:
            return False
        return (
            _linf_dup(candidate, history, self._history_tol)
            or _linf_dup(candidate, pending, self._history_tol)
            or _linf_dup(candidate, batch, self._batch_tol)
        )

    def _to_proposal(self, unit: FloatArray) -> Proposal:
        scenario = self.ctx.space.make_scenario(self.ctx.space.from_unit(unit))
        return Proposal(scenario=scenario, strategy=self.id, phase=self.phase)


def _as_unit(point: npt.ArrayLike, dim: int) -> FloatArray:
    array = np.asarray(point, dtype=np.float64).reshape(-1)
    if array.size != dim:
        msg = f"expected a unit vector of length {dim}, got shape {array.shape}"
        raise errors.ValidationError(msg, context={"dim": dim, "shape": list(array.shape)})
    return array.copy()


def _linf_dup(candidate: FloatArray, others: Sequence[FloatArray], tol: float) -> bool:
    return any(float(np.max(np.abs(candidate - other))) <= tol for other in others)
