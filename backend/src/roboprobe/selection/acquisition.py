"""Acquisition functions: qLogNEI, expected violation, straddle (docs/07 §5).

Layer: Domain (L2).

Implements: FR-SEL-002, FR-SEL-004, T-056a
"""

from __future__ import annotations

import math
import warnings
from typing import cast

import numpy as np
import numpy.typing as npt
from scipy.stats import norm

from roboprobe.selection._compat import (
    AcquisitionFunction,
    LinearMCObjective,
    Model,
    NumericalWarning,
    Tensor,
    qLogNoisyExpectedImprovement,
    torch,
)

__all__ = [
    "ExpectedViolation",
    "Straddle",
    "analytic_expected_violation",
    "analytic_straddle",
    "make_qlognei",
]

_NEGATE_OBJECTIVE: float = -1.0
_HALF: float = 0.5
_LOG_SQRT_TWO_PI: float = _HALF * math.log(2.0 * math.pi)
Q_BATCH_NDIM: int = 3
"""BoTorch candidate tensor rank ``b x 1 x d``."""


def analytic_expected_violation(
    mean: npt.NDArray[np.floating] | float,
    std: npt.NDArray[np.floating] | float,
) -> npt.NDArray[np.float64]:
    """EV = (-mean) * Phi(z) + std * phi(z) with z = -mean/std (docs/07 §5.2).

    Args:
        mean: Latent posterior mean.
        std: Latent posterior std (must be positive).

    Returns:
        Expected violation, same shape as the broadcast of ``mean`` and ``std``.
    """
    mu = np.asarray(mean, dtype=np.float64)
    sigma = np.asarray(std, dtype=np.float64)
    z = -mu / sigma
    return np.asarray((-mu) * norm.cdf(z) + sigma * norm.pdf(z), dtype=np.float64)


def analytic_straddle(
    mean: npt.NDArray[np.floating] | float,
    std: npt.NDArray[np.floating] | float,
    beta: float,
) -> npt.NDArray[np.float64]:
    """Straddle: beta * std - |mean| (docs/07 §5.4).

    Args:
        mean: Latent posterior mean.
        std: Latent posterior std.
        beta: Straddle exploration weight (``selection.probe.beta_straddle``).

    Returns:
        Straddle values.
    """
    mu = np.asarray(mean, dtype=np.float64)
    sigma = np.asarray(std, dtype=np.float64)
    return np.asarray(beta * sigma - np.abs(mu), dtype=np.float64)


def make_qlognei(
    model: Model,
    x_baseline: Tensor,
    x_pending: Tensor | None = None,
) -> qLogNoisyExpectedImprovement:
    """Build qLogNEI on -rho (maximisation form, docs/07 §5.1).

    Args:
        model: Fitted GP on robustness rho.
        x_baseline: Observed inputs ``(n, d)``.
        x_pending: Optional pending inputs ``(n_p, d)``.

    Returns:
        BoTorch ``qLogNoisyExpectedImprovement``.
    """
    weights = torch.tensor([_NEGATE_OBJECTIVE], dtype=x_baseline.dtype, device=x_baseline.device)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NumericalWarning)
        return qLogNoisyExpectedImprovement(
            model,
            X_baseline=x_baseline,
            X_pending=x_pending,
            objective=LinearMCObjective(weights),
            prune_baseline=False,
        )


class ExpectedViolation(AcquisitionFunction):
    """Analytic expected-violation acquisition; ``forward`` maps ``b x 1 x d`` to ``b``.

    Implements: FR-SEL-002
    """

    def __init__(self, model: Model, *, noise_floor: float) -> None:
        """Bind a fitted model.

        Args:
            model: BoTorch model of rho.
            noise_floor: Minimum std (``selection.gp.noise_lower_bound``).
        """
        super().__init__(model)
        self._noise_floor = noise_floor

    def forward(self, x: Tensor) -> Tensor:
        """Evaluate EV at a batch of q=1 candidates.

        Args:
            x: Tensor of shape ``b x 1 x d`` (or ``b x d``).

        Returns:
            Acquisition values, shape ``b``.
        """
        mean, std = _latent_moments(self.model, x, self._noise_floor)
        z = -mean / std
        log_norm = -_HALF * z.square() - _LOG_SQRT_TWO_PI
        return cast(Tensor, (-mean) * torch.special.ndtr(z) + std * torch.exp(log_norm))

    def log_forward(self, x: Tensor) -> Tensor:
        """Log EV, floored at the noise floor for stability.

        Args:
            x: Candidate tensor.

        Returns:
            Log expected violation, shape ``b``.
        """
        return torch.log(self.forward(x).clamp_min(self._noise_floor))


class Straddle(AcquisitionFunction):
    """Level-set straddle beta * std - |mean| (docs/07 §5.4).

    Implements: FR-SEL-004
    """

    def __init__(self, model: Model, *, beta: float, noise_floor: float) -> None:
        """Bind a fitted model.

        Args:
            model: BoTorch model of rho.
            beta: ``selection.probe.beta_straddle``.
            noise_floor: Minimum std.
        """
        super().__init__(model)
        self._beta = beta
        self._noise_floor = noise_floor

    def forward(self, x: Tensor) -> Tensor:
        """Evaluate straddle at a batch of q=1 candidates.

        Args:
            x: Tensor of shape ``b x 1 x d``.

        Returns:
            Acquisition values, shape ``b``.
        """
        mean, std = _latent_moments(self.model, x, self._noise_floor)
        return self._beta * std - mean.abs()


def _latent_moments(model: Model, x: Tensor, noise_floor: float) -> tuple[Tensor, Tensor]:
    x_flat = x.squeeze(-2) if x.dim() == Q_BATCH_NDIM else x
    posterior = model.posterior(x_flat)
    mean = posterior.mean.reshape(x_flat.shape[:-1])  # type: ignore[attr-defined]
    std = posterior.variance.clamp_min(noise_floor**2).sqrt().reshape(mean.shape)  # type: ignore[attr-defined]
    return mean, std
