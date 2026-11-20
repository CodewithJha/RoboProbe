"""S-PROBE refine planner: nominal-ward bisection + Gaussian perturbations (docs/07 §6.1).

Implements: FR-SEL-003, FR-ANA-002
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

import numpy as np
import numpy.typing as npt

from roboprobe.core.settings.selection import ProbeDefaults
from roboprobe.core.types import Observation, Verdict

__all__ = ["RefinePlan", "RefineScheduler"]

FloatArray = npt.NDArray[np.float64]
_MATCH_TOL: Final = 1e-9
_SEGMENT_LO: Final = 0.0
_SEGMENT_HI: Final = 1.0


def _as_float(point: npt.ArrayLike) -> FloatArray:
    return np.asarray(point, dtype=np.float64).reshape(-1).copy()


def _lerp(nominal: FloatArray, medoid: FloatArray, t: float) -> FloatArray:
    return nominal + t * (medoid - nominal)


class RefinePlan:
    """Bisection then perturbations for one mode medoid.

    Args:
        medoid: Failing mode centre in the unit cube.
        nominal: Nominal point in the unit cube.
        bisect_steps: Number of adaptive bisection evaluations.
        perturb_n: Perturbations around the medoid after bisection.
        perturb_std: Isotropic Gaussian std in the unit cube.
        seed: Seed for perturbation draws.
        mode_key: Stable id used in proposal tags / checkpoints.
    """

    def __init__(  # noqa: PLR0913
        self,
        medoid: npt.ArrayLike,
        nominal: npt.ArrayLike,
        *,
        bisect_steps: int | None = None,
        perturb_n: int | None = None,
        perturb_std: float | None = None,
        seed: int = 0,
        mode_key: str = "0",
    ) -> None:
        """Bind refine knobs from :class:`ProbeDefaults` when omitted."""
        defaults = ProbeDefaults()
        self.medoid = _as_float(medoid)
        self.nominal = _as_float(nominal)
        if self.medoid.shape != self.nominal.shape:
            msg = "medoid and nominal must share shape"
            raise ValueError(msg)
        self.bisect_steps = int(
            defaults.refine_bisect_steps if bisect_steps is None else bisect_steps
        )
        self.perturb_n = int(defaults.refine_perturb_n if perturb_n is None else perturb_n)
        self.perturb_std = float(
            defaults.refine_perturb_std if perturb_std is None else perturb_std
        )
        self.seed = int(seed)
        self.mode_key = mode_key
        self._lo = _SEGMENT_LO
        self._hi = _SEGMENT_HI
        self._bisect_done = 0
        self._perturbs_emitted = 0
        self._awaiting: FloatArray | None = None
        self._rng = np.random.default_rng(self.seed)
        self._done = self.bisect_steps == 0 and self.perturb_n == 0

    @property
    def done(self) -> bool:
        """Whether every bisection and perturbation slot has been emitted."""
        return self._done

    @property
    def awaiting(self) -> bool:
        """Whether a bisection proposal is waiting for its verdict."""
        return self._awaiting is not None

    @property
    def closest_failing(self) -> FloatArray:
        """Current estimate of the failing point closest to nominal (``t = hi``)."""
        return _lerp(self.nominal, self.medoid, self._hi)

    def ingest(self, observations: Sequence[Observation]) -> None:
        """Apply verdicts for the awaiting bisection proposal, if any."""
        self._ingest(observations)

    def next_point(self, observations: Sequence[Observation]) -> FloatArray | None:
        """Return the next refine point, ingesting verdicts for this plan only.

        Args:
            observations: Finished runs; only points matching the awaiting proposal update state.

        Returns:
            Next unit-cube point, or ``None`` when the plan is exhausted.
        """
        self.ingest(observations)
        if self._awaiting is not None:
            return None
        if self._bisect_done < self.bisect_steps:
            mid = 0.5 * (self._lo + self._hi)
            point = _lerp(self.nominal, self.medoid, mid)
            self._awaiting = point
            return point.copy()
        if self._perturbs_emitted < self.perturb_n:
            noise = self._rng.normal(0.0, self.perturb_std, size=self.medoid.shape)
            point = np.clip(self.medoid + noise, 0.0, 1.0)
            self._perturbs_emitted += 1
            if self._perturbs_emitted >= self.perturb_n:
                self._done = True
            return point
        self._done = True
        return None

    def state_dict(self) -> dict[str, Any]:
        """JSON-serialisable checkpoint."""
        return {
            "medoid": self.medoid.tolist(),
            "nominal": self.nominal.tolist(),
            "bisect_steps": self.bisect_steps,
            "perturb_n": self.perturb_n,
            "perturb_std": self.perturb_std,
            "seed": self.seed,
            "mode_key": self.mode_key,
            "lo": self._lo,
            "hi": self._hi,
            "bisect_done": self._bisect_done,
            "perturbs_emitted": self._perturbs_emitted,
            "awaiting": None if self._awaiting is None else self._awaiting.tolist(),
            "done": self._done,
            "rng_state": self._rng.bit_generator.state,
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        """Restore :meth:`state_dict` output."""
        self.medoid = _as_float(state["medoid"])
        self.nominal = _as_float(state["nominal"])
        self.bisect_steps = int(state["bisect_steps"])
        self.perturb_n = int(state["perturb_n"])
        self.perturb_std = float(state["perturb_std"])
        self.seed = int(state["seed"])
        self.mode_key = str(state["mode_key"])
        self._lo = float(state["lo"])
        self._hi = float(state["hi"])
        self._bisect_done = int(state["bisect_done"])
        self._perturbs_emitted = int(state["perturbs_emitted"])
        awaiting = state.get("awaiting")
        self._awaiting = None if awaiting is None else _as_float(awaiting)
        self._done = bool(state["done"])
        self._rng = np.random.default_rng(self.seed)
        self._rng.bit_generator.state = state["rng_state"]

    def _ingest(self, observations: Sequence[Observation]) -> None:
        if self._awaiting is None:
            return
        for obs in observations:
            if obs.verdict is Verdict.INVALID:
                continue
            point = np.asarray(obs.x_unit, dtype=np.float64)
            if point.shape != self._awaiting.shape:
                continue
            if float(np.max(np.abs(point - self._awaiting))) > _MATCH_TOL:
                continue
            self._apply_bisect_verdict(obs.verdict)
            self._awaiting = None
            return

    def _apply_bisect_verdict(self, verdict: Verdict) -> None:
        mid = 0.5 * (self._lo + self._hi)
        if verdict is Verdict.FAIL:
            self._hi = mid
        else:
            self._lo = mid
        self._bisect_done += 1
        if self._bisect_done >= self.bisect_steps and self.perturb_n == 0:
            self._done = True


class RefineScheduler:
    """Oldest-unrefined-mode-first queue of :class:`RefinePlan` instances."""

    def __init__(
        self,
        *,
        nominal: npt.ArrayLike,
        bisect_steps: int | None = None,
        perturb_n: int | None = None,
        perturb_std: float | None = None,
        seed: int = 0,
    ) -> None:
        """Create an empty scheduler pinned to ``nominal``."""
        defaults = ProbeDefaults()
        self.nominal = _as_float(nominal)
        self.bisect_steps = int(
            defaults.refine_bisect_steps if bisect_steps is None else bisect_steps
        )
        self.perturb_n = int(defaults.refine_perturb_n if perturb_n is None else perturb_n)
        self.perturb_std = float(
            defaults.refine_perturb_std if perturb_std is None else perturb_std
        )
        self.seed = int(seed)
        self._plans: list[RefinePlan] = []
        self._mode_counter = 0

    @property
    def refine_available(self) -> bool:
        """Whether any plan still has points to emit."""
        return any(not plan.done for plan in self._plans)

    def add_mode(self, medoid: npt.ArrayLike, *, mode_key: str | None = None) -> RefinePlan:
        """Enqueue a new mode; oldest unfinished plans are served first.

        Args:
            medoid: Mode centre in the unit cube.
            mode_key: Optional stable key; defaults to a counter.

        Returns:
            The created plan.
        """
        key = mode_key if mode_key is not None else str(self._mode_counter)
        self._mode_counter += 1
        plan = RefinePlan(
            medoid,
            self.nominal,
            bisect_steps=self.bisect_steps,
            perturb_n=self.perturb_n,
            perturb_std=self.perturb_std,
            seed=self.seed + self._mode_counter,
            mode_key=key,
        )
        self._plans.append(plan)
        return plan

    def ingest(self, observations: Sequence[Observation]) -> None:
        """Ingest verdicts into every plan without emitting new points."""
        for plan in self._plans:
            plan.ingest(observations)

    def next_point(self, observations: Sequence[Observation]) -> FloatArray | None:
        """Next refine point from the oldest unfinished plan."""
        self.ingest(observations)
        for plan in self._plans:
            if plan.done:
                continue
            point = plan.next_point([])
            if point is not None:
                return point
            if plan.awaiting:
                return None
        return None

    def state_dict(self) -> dict[str, Any]:
        """JSON-serialisable checkpoint."""
        return {
            "nominal": self.nominal.tolist(),
            "bisect_steps": self.bisect_steps,
            "perturb_n": self.perturb_n,
            "perturb_std": self.perturb_std,
            "seed": self.seed,
            "mode_counter": self._mode_counter,
            "plans": [plan.state_dict() for plan in self._plans],
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        """Restore :meth:`state_dict` output."""
        self.nominal = _as_float(state["nominal"])
        self.bisect_steps = int(state["bisect_steps"])
        self.perturb_n = int(state["perturb_n"])
        self.perturb_std = float(state["perturb_std"])
        self.seed = int(state["seed"])
        self._mode_counter = int(state["mode_counter"])
        self._plans = []
        for payload in state["plans"]:
            plan = RefinePlan(
                payload["medoid"],
                payload["nominal"],
                bisect_steps=payload["bisect_steps"],
                perturb_n=payload["perturb_n"],
                perturb_std=payload["perturb_std"],
                seed=payload["seed"],
                mode_key=payload["mode_key"],
            )
            plan.load_state_dict(payload)
            self._plans.append(plan)
