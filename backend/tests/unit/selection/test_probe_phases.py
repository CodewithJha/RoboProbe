"""Unit tests for S-PROBE PhaseController (T-059a, docs/07 §6.1)."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from roboprobe.core.settings.selection import ProbeDefaults, ProbeWeights
from roboprobe.selection.probe_phases import PhaseController, PhaseView

pytestmark = pytest.mark.unit

CHI2_ALPHA = 0.01
FREQ_DRAWS = 20_000
FREQ_SEEDS = (0, 1, 2, 3, 4)


def _controller(**overrides: object) -> PhaseController:
    defaults = ProbeDefaults()
    return PhaseController(
        n0=12,
        weights=overrides.get("weights", defaults.weights),  # type: ignore[arg-type]
        epsilon=overrides.get("epsilon", defaults.epsilon),  # type: ignore[arg-type]
        adapt_window=overrides.get("adapt_window", defaults.adapt_window),  # type: ignore[arg-type]
        adapt_shift=overrides.get("adapt_shift", defaults.adapt_shift),  # type: ignore[arg-type]
        mode_search_floor=overrides.get("mode_search_floor", defaults.mode_search_floor),  # type: ignore[arg-type]
    )


def test_warmup_then_falsify_then_mixed() -> None:
    ctrl = _controller(epsilon=0.0)
    assert ctrl.choose_phase(np.random.default_rng(0), PhaseView(0, False, False)) == "warmup"
    assert ctrl.choose_phase(np.random.default_rng(0), PhaseView(11, False, False)) == "warmup"
    assert ctrl.choose_phase(np.random.default_rng(0), PhaseView(12, False, False)) == "falsify"
    phase = ctrl.choose_phase(np.random.default_rng(0), PhaseView(12, True, True))
    assert phase in {"mode_search", "boundary", "refine"}


def test_refine_unavailable_renormalises_weights() -> None:
    weights = ProbeWeights(mode_search=0.6, boundary=0.25, refine=0.15)
    ctrl = PhaseController(n0=1, weights=weights, epsilon=0.0)
    draws = FREQ_DRAWS * 3
    observed = np.zeros(2, dtype=np.float64)
    for seed in FREQ_SEEDS:
        rng = np.random.default_rng(seed)
        for _ in range(draws):
            phase = ctrl.choose_phase(rng, PhaseView(1, True, False))
            assert phase != "refine"
            observed[0 if phase == "mode_search" else 1] += 1.0
    total = float(observed.sum())
    expected = np.array([total * (0.6 / 0.85), total * (0.25 / 0.85)])
    assert stats.chisquare(observed, expected).pvalue > CHI2_ALPHA


@pytest.mark.parametrize("seed", FREQ_SEEDS)
def test_empirical_mixed_frequencies_match_weights(seed: int) -> None:
    defaults = ProbeDefaults()
    ctrl = PhaseController(n0=1, weights=defaults.weights, epsilon=defaults.epsilon)
    rng = np.random.default_rng(seed)
    counts = {"mode_search": 0, "boundary": 0, "refine": 0, "explore": 0}
    for _ in range(FREQ_DRAWS):
        phase = ctrl.choose_phase(rng, PhaseView(1, True, True))
        counts[phase] += 1
    eps = defaults.epsilon
    remain = 1.0 - eps
    expected = [
        FREQ_DRAWS * remain * defaults.weights.mode_search,
        FREQ_DRAWS * remain * defaults.weights.boundary,
        FREQ_DRAWS * remain * defaults.weights.refine,
        FREQ_DRAWS * eps,
    ]
    observed = [
        counts["mode_search"],
        counts["boundary"],
        counts["refine"],
        counts["explore"],
    ]
    assert stats.chisquare(observed, expected).pvalue > CHI2_ALPHA


def test_adaptive_rule_shifts_exactly_once_per_window() -> None:
    defaults = ProbeDefaults()
    ctrl = PhaseController(
        n0=1,
        weights=defaults.weights,
        adapt_window=defaults.adapt_window,
        adapt_shift=defaults.adapt_shift,
        mode_search_floor=defaults.mode_search_floor,
    )
    before = ctrl.weights
    for _ in range(defaults.adapt_window - 1):
        ctrl.record_outcome("mode_search", False)
        assert ctrl.weights == before
    ctrl.record_outcome("mode_search", False)
    after = ctrl.weights
    assert after["mode_search"] == pytest.approx(before["mode_search"] - defaults.adapt_shift)
    assert after["boundary"] == pytest.approx(before["boundary"] + defaults.adapt_shift)
    assert after["refine"] == pytest.approx(before["refine"])


def test_adaptive_rule_respects_mode_search_floor() -> None:
    defaults = ProbeDefaults()
    ctrl = PhaseController(
        n0=1,
        weights=ProbeWeights(mode_search=0.25, boundary=0.60, refine=0.15),
        adapt_window=3,
        adapt_shift=defaults.adapt_shift,
        mode_search_floor=defaults.mode_search_floor,
    )
    for _ in range(3):
        ctrl.record_outcome("mode_search", False)
    assert ctrl.weights["mode_search"] == pytest.approx(defaults.mode_search_floor)
    assert ctrl.weights["boundary"] == pytest.approx(0.65)


def test_productive_mode_search_skips_adapt() -> None:
    defaults = ProbeDefaults()
    ctrl = PhaseController(n0=1, adapt_window=defaults.adapt_window)
    before = ctrl.weights
    for i in range(defaults.adapt_window):
        ctrl.record_outcome("mode_search", i == defaults.adapt_window // 2)
    assert ctrl.weights == before


def test_state_dict_round_trip() -> None:
    ctrl = _controller()
    for _ in range(5):
        ctrl.record_outcome("mode_search", False)
    payload = ctrl.state_dict()
    clone = PhaseController(n0=1)
    clone.load_state_dict(payload)
    assert clone.state_dict() == payload
    assert clone.weights == ctrl.weights
