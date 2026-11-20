"""Kriging Believer batch proposals (T-056c)."""

from __future__ import annotations

import numpy as np
import pytest

from roboprobe.core.settings.selection import AcquisitionDefaults, GpDefaults, ProbeDefaults
from roboprobe.selection._compat import torch
from roboprobe.selection.acquisition import ExpectedViolation, Straddle
from roboprobe.selection.optimize import kriging_believer_batch, optimize, round_integers
from roboprobe.selection.surrogate import RobustnessGP

pytestmark = [
    pytest.mark.unit,
    pytest.mark.filterwarnings("ignore:.*torch.jit.script.*:FutureWarning"),
]

D = 2
Q = 4


def _gp() -> RobustnessGP:
    rng = np.random.default_rng(0)
    x = rng.random((18, D))
    y = np.sin(2 * np.pi * x[:, 0]) * x[:, 1] - 0.15
    model = RobustnessGP(D, seed=0)
    model.fit(x, y)
    return model


def test_q4_pairwise_distinct_and_seeded() -> None:
    gp = _gp()
    floor = GpDefaults().noise_lower_bound
    settings = AcquisitionDefaults(num_restarts=2, raw_samples=32, maxiter=15)

    def factory(model: RobustnessGP) -> ExpectedViolation:
        return ExpectedViolation(model.botorch_model(), noise_floor=floor)

    gen_a = torch.Generator().manual_seed(21)
    gen_b = torch.Generator().manual_seed(21)
    batch_a = kriging_believer_batch(gp, factory, Q, settings=settings, generator=gen_a)
    batch_b = kriging_believer_batch(gp, factory, Q, settings=settings, generator=gen_b)
    assert len(batch_a) == Q
    for i, p in enumerate(batch_a):
        for j, q in enumerate(batch_a):
            if i >= j:
                continue
            assert float(np.max(np.abs(p - q))) > settings.dedupe_tol
    for a, b in zip(batch_a, batch_b, strict=True):
        np.testing.assert_allclose(a, b)


def test_integer_rounding_hook() -> None:
    x = np.array([0.49, 0.51])
    np.testing.assert_allclose(round_integers(x, (0, 1)), [0.0, 1.0])


def test_tabu_avoids_infeasible_peak() -> None:
    gp = _gp()
    probe = ProbeDefaults()
    acq = Straddle(
        gp.botorch_model(),
        beta=probe.beta_straddle,
        noise_floor=GpDefaults().noise_lower_bound,
    )
    settings = AcquisitionDefaults(num_restarts=2, raw_samples=24, maxiter=10)

    def forbidden(point: np.ndarray) -> bool:
        return float(point[0]) >= 0.2

    gen = torch.Generator().manual_seed(3)
    x = optimize(acq, d=D, settings=settings, generator=gen, is_feasible=forbidden)
    assert x[0] >= 0.2
    assert 0.0 <= x[1] <= 1.0
