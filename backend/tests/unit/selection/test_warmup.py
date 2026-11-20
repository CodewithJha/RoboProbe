"""Warm-up sizing helper (shared by S-BO / S-LSE / S-PROBE)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from roboprobe.core.settings.selection import ProbeDefaults
from roboprobe.selection.warmup import WarmupState, warmup_size

pytestmark = pytest.mark.unit


def test_warmup_size_matches_doc_formula() -> None:
    probe = ProbeDefaults()
    budget, dim = 100, 6
    expected = max(probe.n0_min_factor * dim, math.ceil(probe.n0_fraction * budget))
    assert warmup_size(budget, dim) == expected == 12


def test_warmup_state_deterministic() -> None:
    rng = np.random.default_rng(0)
    a = WarmupState(2, seed=3)
    b = WarmupState(2, seed=3)
    pa = np.stack(a.sample(4, rng))
    pb = np.stack(b.sample(4, np.random.default_rng(0)))
    np.testing.assert_allclose(pa, pb)
    blob = a.state_dict()
    clone = WarmupState(2, seed=3)
    clone.load_state_dict(blob)
    assert clone.index == a.index
