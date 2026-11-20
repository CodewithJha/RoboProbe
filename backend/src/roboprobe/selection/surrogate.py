"""Gaussian-process surrogate on continuous robustness rho (docs/07 §4, docs/05 §4).

Layer: Domain (L2). BoTorch/GPyTorch stay inside ``selection``.

Implements: FR-SEL-002, FR-RSK-001, NFR-PERF-002, NFR-SCAL-001, T-055a, T-055b
"""

from __future__ import annotations

import os
from typing import Literal, cast

import numpy as np
import numpy.typing as npt
from scipy.stats import norm

from roboprobe.core.clock import Clock, SystemClock
from roboprobe.core.errors import ModelFitError
from roboprobe.core.metrics_registry import Metrics
from roboprobe.core.seeding import derive_seed
from roboprobe.core.settings.selection import GpDefaults
from roboprobe.selection._compat import (
    ExactMarginalLogLikelihood,
    GaussianLikelihood,
    GreaterThan,
    MaternKernel,
    ScaleKernel,
    SingleTaskGP,
    Standardize,
    fit_gpytorch_mll,
    gpytorch,
    torch,
)

__all__ = ["RobustnessGP", "select_training_subset"]

MATERN_NU: float = 2.5
"""Matern nu = 5/2 (docs/07 §4)."""

BOUNDARY_BAND: float = 0.2
"""|rho| band kept under the scale guard (docs/07 §4) until ``GpDefaults.boundary_band`` exists."""

_OUTCOME_DIM: int = 1
_FIT_ATTEMPTS: int = 2


def select_training_subset(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    max_points: int,
    *,
    boundary_band: float,
    order: npt.NDArray[np.intp] | None = None,
) -> npt.NDArray[np.intp]:
    """Pick at most ``max_points`` informative rows (docs/07 §4).

    Priority, most-recent first within each class: failures (``y < 0``), then
    absolute rho below ``boundary_band``, then remaining rows.

    Args:
        x: Inputs ``(n, d)`` (unused except for length checks).
        y: Robustness values ``(n,)``.
        max_points: Cap on the returned index set.
        boundary_band: Half-width of the |rho| band treated as the decision boundary.
        order: Recency ranks, larger = newer. Defaults to row index.

    Returns:
        Indices into ``x``/``y``, length ``min(n, max_points)``.
    """
    del x
    n = int(y.shape[0])
    if n <= max_points:
        return np.arange(n, dtype=np.intp)
    ranks = np.arange(n, dtype=np.intp) if order is None else order
    newest_first = np.argsort(-ranks, kind="stable")
    y_new = y[newest_first]
    failures = newest_first[y_new < 0]
    boundary = newest_first[np.abs(y_new) < boundary_band]
    picked: list[int] = []
    seen: set[int] = set()
    for idx in np.concatenate([failures, boundary, newest_first]):
        i = int(idx)
        if i in seen:
            continue
        seen.add(i)
        picked.append(i)
        if len(picked) == max_points:
            break
    return np.asarray(picked, dtype=np.intp)


class RobustnessGP:
    """``SingleTaskGP`` + Matern-5/2 ARD on unit-cube inputs (docs/07 §4).

    Implements: FR-SEL-002, FR-RSK-001
    """

    def __init__(  # noqa: PLR0913
        self,
        d: int,
        *,
        noise: Literal["learned", "fixed"] = "learned",
        seed: int = 0,
        gp: GpDefaults | None = None,
        metrics: Metrics | None = None,
        clock: Clock | None = None,
        boundary_band: float | None = None,
    ) -> None:
        """Configure the surrogate; call :meth:`fit` before predicting.

        Args:
            d: Input dimension.
            noise: ``learned`` homoscedastic noise, or ``fixed`` at the noise floor.
            seed: Root seed; combined with ``n_obs`` for the fit generator.
            gp: ``selection.gp`` settings (defaults if omitted).
            metrics: Optional Prometheus bundle; observes ``gp_fit_seconds``.
            clock: Injected clock for fit timing.
            boundary_band: Scale-guard |rho| band; defaults to :data:`BOUNDARY_BAND`.
        """
        if d < 1:
            msg = "RobustnessGP dimension must be positive"
            raise ValueError(msg)
        self.d = d
        self._noise_mode = noise
        self._seed = seed
        self._gp = gp if gp is not None else GpDefaults()
        self._metrics = metrics
        self._clock = clock if clock is not None else SystemClock()
        self._boundary_band = (
            boundary_band
            if boundary_band is not None
            else float(getattr(self._gp, "boundary_band", BOUNDARY_BAND))
        )
        self.subsampled: bool = False
        self._model: SingleTaskGP | None = None

    def fit(self, x: npt.NDArray[np.floating], y: npt.NDArray[np.floating]) -> None:
        """Fit on non-INVALID (finite-``y``) rows, with scale guard and retry.

        Args:
            x: Inputs ``(n, d)`` in the unit cube.
            y: Robustness ``(n,)``. Non-finite entries are dropped (INVALID).

        Raises:
            ModelFitError: Both fit attempts failed and no previous model exists.
        """
        x_arr, y_arr = _finite_observations(
            np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
        )
        if x_arr.shape[1] != self.d:
            msg = f"expected d={self.d}, got {x_arr.shape[1]}"
            raise ValueError(msg)
        n_obs = int(x_arr.shape[0])
        idx = select_training_subset(
            x_arr,
            y_arr,
            self._gp.max_points,
            boundary_band=self._boundary_band,
        )
        self.subsampled = n_obs > self._gp.max_points
        x_fit = x_arr[idx]
        y_fit = y_arr[idx]
        threads = min(self._gp.torch_threads, os.cpu_count() or 1)
        torch.set_num_threads(threads)
        torch.set_default_dtype(torch.float64)
        train_x = torch.as_tensor(x_fit, dtype=torch.float64)
        train_y = torch.as_tensor(y_fit, dtype=torch.float64).unsqueeze(-1)
        gen = torch.Generator(device="cpu")
        gen.manual_seed(derive_seed(self._seed, n_obs))
        previous = self._model
        started = self._clock.monotonic()
        last_error: Exception | None = None
        for attempt in range(_FIT_ATTEMPTS):
            try:
                with torch.random.fork_rng():
                    torch.manual_seed(int(gen.initial_seed()) + attempt)
                    likelihood = GaussianLikelihood(
                        noise_constraint=GreaterThan(self._gp.noise_lower_bound)
                    )
                    if self._noise_mode == "fixed":
                        likelihood.noise = torch.tensor(
                            self._gp.noise_lower_bound, dtype=torch.float64
                        )
                        likelihood.raw_noise.requires_grad_(False)
                    covar = ScaleKernel(
                        MaternKernel(nu=MATERN_NU, ard_num_dims=self.d),
                    )
                    model = SingleTaskGP(
                        train_x,
                        train_y,
                        likelihood=likelihood,
                        covar_module=covar,
                        outcome_transform=Standardize(m=_OUTCOME_DIM),
                    )
                    mll = ExactMarginalLogLikelihood(model.likelihood, model)
                    with gpytorch.settings.cholesky_jitter(self._gp.noise_lower_bound):
                        fit_gpytorch_mll(mll)
                model.eval()
                self._model = model
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                self._model = previous
        elapsed = self._clock.monotonic() - started
        if self._metrics is not None:
            self._metrics.gp_fit_seconds.observe(elapsed)
        if last_error is not None:
            msg = "fit failed"
            raise ModelFitError(msg) from last_error

    def predict(
        self, x: npt.NDArray[np.floating]
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        """Latent posterior mean and std (observation noise excluded).

        Args:
            x: Query inputs ``(n, d)``.

        Returns:
            ``(mean, std)`` each of shape ``(n,)``.
        """
        mean, var = self._posterior_moments(x, observation_noise=False)
        return mean, np.sqrt(var)

    def predict_total_std(self, x: npt.NDArray[np.floating]) -> npt.NDArray[np.float64]:
        """Posterior std including observation noise (risk map).

        Args:
            x: Query inputs ``(n, d)``.

        Returns:
            Total standard deviation, shape ``(n,)``.
        """
        _, var = self._posterior_moments(x, observation_noise=True)
        return np.sqrt(var)

    def p_fail(self, x: npt.NDArray[np.floating]) -> npt.NDArray[np.float64]:
        """Phi(-mean/std) using latent std (docs/07 §4, docs/09 §5.1).

        Args:
            x: Query inputs ``(n, d)``.

        Returns:
            Failure probabilities in ``[0, 1]``.
        """
        mean, std = self.predict(x)
        std_safe = np.maximum(std, self._gp.noise_lower_bound)
        z = -mean / std_safe
        return np.asarray(norm.cdf(z), dtype=np.float64)

    @property
    def lengthscales(self) -> npt.NDArray[np.float64]:
        """ARD length-scales of the Matern kernel."""
        model = self._require_model()
        ls = model.covar_module.base_kernel.lengthscale.detach().cpu().numpy()
        return np.asarray(ls, dtype=np.float64).reshape(-1)

    def botorch_model(self) -> SingleTaskGP:
        """Fitted BoTorch model (eval mode)."""
        return self._require_model()

    def condition_on_observations(
        self,
        x: npt.NDArray[np.floating],
        y: npt.NDArray[np.floating],
    ) -> RobustnessGP:
        """Fantasy-condition without refitting hyper-parameters (docs/07 §5.6).

        Args:
            x: New inputs ``(k, d)`` or ``(d,)``.
            y: Pseudo-observations (typically the latent mean), shape ``(k,)`` or scalar.

        Returns:
            A new :class:`RobustnessGP` sharing hyper-parameters.
        """
        model = self._require_model()
        x_t = torch.as_tensor(np.asarray(x, dtype=np.float64), dtype=torch.float64)
        y_t = torch.as_tensor(np.asarray(y, dtype=np.float64), dtype=torch.float64)
        if x_t.ndim == 1:
            x_t = x_t.unsqueeze(0)
        if y_t.ndim == 0:
            y_t = y_t.unsqueeze(0)
        if y_t.ndim == 1:
            y_t = y_t.unsqueeze(-1)
        model.posterior(x_t)
        fantasised = model.condition_on_observations(x_t, y_t)
        clone = RobustnessGP(
            self.d,
            noise=self._noise_mode,
            seed=self._seed,
            gp=self._gp,
            metrics=self._metrics,
            clock=self._clock,
            boundary_band=self._boundary_band,
        )
        clone.subsampled = self.subsampled
        clone._model = cast(SingleTaskGP, fantasised.eval())
        return clone

    def _require_model(self) -> SingleTaskGP:
        if self._model is None:
            msg = "not fitted"
            raise ModelFitError(msg)
        return self._model

    def _posterior_moments(
        self,
        x: npt.NDArray[np.floating],
        *,
        observation_noise: bool,
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        model = self._require_model()
        x_t = torch.as_tensor(np.asarray(x, dtype=np.float64), dtype=torch.float64)
        if x_t.ndim == 1:
            x_t = x_t.unsqueeze(0)
        with torch.no_grad():
            posterior = model.posterior(x_t, observation_noise=observation_noise)
            mean = posterior.mean.reshape(-1)
            var = posterior.variance.reshape(-1).clamp_min(0.0)
        return (
            np.asarray(mean.cpu().numpy(), dtype=np.float64),
            np.asarray(var.cpu().numpy(), dtype=np.float64),
        )


def _finite_observations(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    y_flat = np.asarray(y, dtype=np.float64).reshape(-1)
    mask = np.isfinite(y_flat)
    x_kept = np.asarray(x, dtype=np.float64)[mask]
    y_kept = y_flat[mask]
    if x_kept.size == 0:
        msg = "no observations"
        raise ModelFitError(msg)
    return x_kept, y_kept
