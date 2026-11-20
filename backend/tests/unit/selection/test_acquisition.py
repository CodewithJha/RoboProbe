"""qLogNEI, expected violation and straddle (T-056a)."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.stats import norm

from roboprobe.core.settings.selection import AcquisitionDefaults, GpDefaults, ProbeDefaults
from roboprobe.selection._compat import torch
from roboprobe.selection.acquisition import (
    ExpectedViolation,
    Straddle,
    analytic_expected_violation,
    analytic_straddle,
    make_qlognei,
)
from roboprobe.selection.optimize import optimize
from roboprobe.selection.surrogate import RobustnessGP

pytestmark = [
    pytest.mark.unit,
    pytest.mark.filterwarnings("ignore:.*torch.jit.script.*:FutureWarning"),
]

D = 2


def test_ev_and_straddle_match_hand_values() -> None:
    mu, sigma = -0.4, 0.5
    z = -mu / sigma
    hand_ev = (-mu) * norm.cdf(z) + sigma * norm.pdf(z)
    np.testing.assert_allclose(analytic_expected_violation(mu, sigma), hand_ev)
    beta = ProbeDefaults().beta_straddle
    np.testing.assert_allclose(analytic_straddle(mu, sigma, beta), beta * sigma - abs(mu))


def test_ev_straddle_match_gp_posterior() -> None:
    rng = np.random.default_rng(0)
    x = rng.random((24, D))
    y = np.sin(2 * np.pi * x[:, 0]) - 0.2
    gp = RobustnessGP(D, seed=0)
    gp.fit(x, y)
    q = np.array([[0.2, 0.3], [0.7, 0.1]])
    mean, std = gp.predict(q)
    settings = GpDefaults()
    probe = ProbeDefaults()
    xt = torch.as_tensor(q, dtype=torch.float64).unsqueeze(1)
    ev = ExpectedViolation(gp.botorch_model(), noise_floor=settings.noise_lower_bound)
    st = Straddle(
        gp.botorch_model(), beta=probe.beta_straddle, noise_floor=settings.noise_lower_bound
    )
    np.testing.assert_allclose(
        ev.forward(xt).detach().numpy(),
        analytic_expected_violation(mean, std),
        rtol=1e-5,
        atol=1e-5,
    )
    np.testing.assert_allclose(
        st.forward(xt).detach().numpy(),
        analytic_straddle(mean, std, probe.beta_straddle),
        rtol=1e-5,
        atol=1e-5,
    )


def test_qlognei_avoids_pending_point() -> None:
    rng = np.random.default_rng(1)
    x = rng.random((20, D))
    y = x[:, 0] - 0.8
    gp = RobustnessGP(D, seed=1)
    gp.fit(x, y)
    pending = torch.tensor([[0.15, 0.15]], dtype=torch.float64)
    baseline = torch.as_tensor(x, dtype=torch.float64)
    acq = make_qlognei(gp.botorch_model(), baseline, x_pending=pending)
    settings = AcquisitionDefaults(num_restarts=2, raw_samples=32, maxiter=20)
    gen = torch.Generator().manual_seed(11)
    x_star = optimize(acq, d=D, settings=settings, generator=gen, existing=[pending.numpy()[0]])
    assert float(np.max(np.abs(x_star - pending.numpy()[0]))) > settings.dedupe_tol
