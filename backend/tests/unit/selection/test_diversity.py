"""Diversity penalty and mode cache (T-056b)."""

from __future__ import annotations

import numpy as np
import pytest

from roboprobe.core.settings.selection import ProbeDefaults, SelectionDefaults
from roboprobe.selection.diversity import ModeCache, diversity_penalty

pytestmark = [
    pytest.mark.unit,
    pytest.mark.filterwarnings("ignore:.*torch.jit.script.*:FutureWarning"),
]


def test_penalty_zero_at_medoid_one_far_away() -> None:
    probe = ProbeDefaults()
    medoids = np.array([[0.2, 0.2]])
    ell = np.ones(2)
    at = diversity_penalty(medoids, medoids, ell, probe.kappa_radius)
    far = diversity_penalty(np.array([[0.9, 0.9]]), medoids, ell, probe.kappa_radius)
    assert at[0] == pytest.approx(0.0)
    assert far[0] > at[0]
    assert far[0] == pytest.approx(1.0, abs=0.2)


def test_empty_medoids_penalty_is_one() -> None:
    assert diversity_penalty(np.array([[0.1, 0.2]]), np.empty((0, 2)), np.ones(2), 0.5)[0] == 1.0


def test_mode_cache_refresh_cadence() -> None:
    refresh = SelectionDefaults().mode_cache_refresh_every
    cache = ModeCache(refresh_every=refresh, min_cluster_size=3)
    rng = np.random.default_rng(0)
    a = 0.1 + 0.02 * rng.random((12, 2))
    b = 0.8 + 0.02 * rng.random((12, 2))
    fail = np.vstack([a, b])
    first = cache.update(fail, n_obs=refresh).copy()
    assert first.shape[0] >= 1
    mutated = fail + 0.3
    cached = cache.update(mutated, n_obs=refresh + refresh - 1)
    np.testing.assert_array_equal(cached, first)
    refreshed = cache.update(mutated, n_obs=2 * refresh)
    assert refreshed.shape[0] >= 1
    assert not np.allclose(refreshed, first)
