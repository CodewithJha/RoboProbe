"""S-PROBE phase state machine (docs/07 §6.1).

Implements: FR-SEL-003, FR-SEL-008
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import numpy as np

from roboprobe.core.settings.selection import ProbeDefaults, ProbeWeights
from roboprobe.core.types import Phase

__all__ = ["PhaseController", "PhaseView"]

_MIXED_PHASES: Final[tuple[Phase, ...]] = ("mode_search", "boundary", "refine")


@dataclass(frozen=True, slots=True)
class PhaseView:
    """Inputs for one phase decision (docs/07 §6.1)."""

    n_obs: int
    has_failure: bool
    refine_available: bool


class PhaseController:
    """Pure, serialisable Warmup → Falsify → Mixed phase chooser.

    Args:
        n0: Warm-up size before Falsify.
        weights: Initial Mixed-phase mixture (must sum to 1).
        epsilon: Probability of Explore once Mixed.
        adapt_window: ModeSearch outcomes kept for the adaptive rule.
        adapt_shift: Weight moved ModeSearch → Boundary when the window is unproductive.
        mode_search_floor: Floor on ModeSearch after adaptive shifts.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        n0: int,
        weights: ProbeWeights | None = None,
        epsilon: float | None = None,
        adapt_window: int | None = None,
        adapt_shift: float | None = None,
        mode_search_floor: float | None = None,
    ) -> None:
        """Bind defaults from :class:`ProbeDefaults` when overrides are omitted."""
        defaults = ProbeDefaults()
        if n0 < 1:
            msg = f"n0 must be >= 1, got {n0}"
            raise ValueError(msg)
        self._n0 = n0
        probe_weights = weights if weights is not None else defaults.weights
        self._mode_search = float(probe_weights.mode_search)
        self._boundary = float(probe_weights.boundary)
        self._refine = float(probe_weights.refine)
        self._epsilon = float(defaults.epsilon if epsilon is None else epsilon)
        self._adapt_window = int(defaults.adapt_window if adapt_window is None else adapt_window)
        self._adapt_shift = float(defaults.adapt_shift if adapt_shift is None else adapt_shift)
        self._mode_search_floor = float(
            defaults.mode_search_floor if mode_search_floor is None else mode_search_floor
        )
        self._mode_search_outcomes: list[bool] = []

    @property
    def weights(self) -> dict[str, float]:
        """Current Mixed-phase weights (before Refine renormalisation)."""
        return {
            "mode_search": self._mode_search,
            "boundary": self._boundary,
            "refine": self._refine,
        }

    def choose_phase(self, rng: np.random.Generator, state: PhaseView) -> Phase:
        """Select the phase for one proposal slot.

        Args:
            rng: Injected generator (never the global RNG).
            state: Observation counts and Refine availability.

        Returns:
            Phase literal stored on the proposal.
        """
        if state.n_obs < self._n0:
            return "warmup"
        if not state.has_failure:
            return "falsify"
        if rng.random() < self._epsilon:
            return "explore"
        probs = self._mixed_probs(refine_available=state.refine_available)
        index = int(rng.choice(len(_MIXED_PHASES), p=probs))
        return _MIXED_PHASES[index]

    def record_outcome(self, phase: Phase, new_mode: bool) -> None:
        """Record whether a ModeSearch proposal found a new mode; apply the adaptive rule.

        Args:
            phase: Phase that produced the proposal.
            new_mode: Whether the outcome introduced a new failure mode.
        """
        if phase != "mode_search":
            return
        self._mode_search_outcomes.append(bool(new_mode))
        if len(self._mode_search_outcomes) > self._adapt_window:
            self._mode_search_outcomes = self._mode_search_outcomes[-self._adapt_window :]
        if len(self._mode_search_outcomes) < self._adapt_window:
            return
        if any(self._mode_search_outcomes):
            return
        self._apply_adapt_shift()
        self._mode_search_outcomes.clear()

    def state_dict(self) -> dict[str, Any]:
        """JSON-serialisable checkpoint."""
        return {
            "n0": self._n0,
            "mode_search": self._mode_search,
            "boundary": self._boundary,
            "refine": self._refine,
            "epsilon": self._epsilon,
            "adapt_window": self._adapt_window,
            "adapt_shift": self._adapt_shift,
            "mode_search_floor": self._mode_search_floor,
            "mode_search_outcomes": list(self._mode_search_outcomes),
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        """Restore :meth:`state_dict` output.

        Args:
            state: Previously returned checkpoint.
        """
        self._n0 = int(state["n0"])
        self._mode_search = float(state["mode_search"])
        self._boundary = float(state["boundary"])
        self._refine = float(state["refine"])
        self._epsilon = float(state["epsilon"])
        self._adapt_window = int(state["adapt_window"])
        self._adapt_shift = float(state["adapt_shift"])
        self._mode_search_floor = float(state["mode_search_floor"])
        self._mode_search_outcomes = [bool(x) for x in state.get("mode_search_outcomes", [])]

    def _mixed_probs(self, *, refine_available: bool) -> list[float]:
        mode_search = self._mode_search
        boundary = self._boundary
        refine = self._refine if refine_available else 0.0
        total = mode_search + boundary + refine
        if total <= 0.0:
            # Degenerate: equal mass over available Mixed phases.
            available = 2 + int(refine_available)
            return [1.0 / available if i < available else 0.0 for i in range(len(_MIXED_PHASES))]
        return [mode_search / total, boundary / total, refine / total]

    def _apply_adapt_shift(self) -> None:
        movable = max(0.0, self._mode_search - self._mode_search_floor)
        shift = min(self._adapt_shift, movable)
        self._mode_search -= shift
        self._boundary += shift
