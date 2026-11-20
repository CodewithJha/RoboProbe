"""Diversity penalty over known failure-mode medoids (docs/07 §5.3).

Layer: Domain (L2). Clustering is local (no ``analysis`` import).

Implements: FR-SEL-003, T-056b
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from roboprobe.selection._compat import HDBSCAN, AcquisitionFunction, Model, Tensor, torch
from roboprobe.selection.acquisition import Q_BATCH_NDIM, ExpectedViolation

__all__ = ["DiversityPenalizedEV", "ModeCache", "diversity_penalty"]

PENALTY_FLOOR: float = 1e-12
"""log(penalty + eps) floor from docs/07 §5.3."""

_HALF: float = 0.5
_POINT_NDIM: int = 2
_DEFAULT_MIN_CLUSTER_SIZE: int = 3
"""Cheap HDBSCAN size matching docs/05 ``FailureClusterer``."""


def diversity_penalty(
    x: npt.NDArray[np.floating],
    medoids: npt.NDArray[np.floating],
    lengthscales: npt.NDArray[np.floating],
    kappa_radius: float,
) -> npt.NDArray[np.float64]:
    """Product over modes of (1 - exp(-0.5 * mahalanobis^2)); radius = kappa * lengthscale.

    Empty medoids yield 1 (no penalty). At a medoid the product is 0.

    Args:
        x: Query points ``(n, d)`` or ``(d,)``.
        medoids: Known mode centres ``(k, d)``.
        lengthscales: ARD length-scales ``(d,)``.
        kappa_radius: ``selection.probe.kappa_radius``.

    Returns:
        Penalty in ``[0, 1]``, shape ``(n,)``.
    """
    pts = np.atleast_2d(np.asarray(x, dtype=np.float64))
    modes = np.atleast_2d(np.asarray(medoids, dtype=np.float64))
    if modes.size == 0:
        return np.ones(pts.shape[0], dtype=np.float64)
    radii = kappa_radius * np.asarray(lengthscales, dtype=np.float64).reshape(1, -1)
    delta = (pts[:, None, :] - modes[None, :, :]) / radii
    log_kernel = -_HALF * np.sum(delta**2, axis=-1)
    per_mode = 1.0 - np.exp(log_kernel)
    return np.prod(per_mode, axis=1)


class ModeCache:
    """HDBSCAN medoids of failing points, refreshed every ``n`` observations.

    Implements: FR-SEL-003
    """

    def __init__(
        self,
        refresh_every: int,
        *,
        min_cluster_size: int = _DEFAULT_MIN_CLUSTER_SIZE,
    ) -> None:
        """Create an empty cache.

        Args:
            refresh_every: ``selection.mode_cache_refresh_every``.
            min_cluster_size: HDBSCAN minimum cluster size.
        """
        self.refresh_every = refresh_every
        self.min_cluster_size = min_cluster_size
        self.medoids: npt.NDArray[np.float64] = np.empty((0, 0), dtype=np.float64)
        self._last_n: int | None = None

    def update(self, x_fail: npt.NDArray[np.floating], n_obs: int) -> npt.NDArray[np.float64]:
        """Refresh medoids when ``n_obs`` advanced by ``refresh_every``.

        Args:
            x_fail: Failing inputs ``(n_f, d)`` in the unit cube.
            n_obs: Current observation count (cadence key).

        Returns:
            Medoid array ``(k, d)``.
        """
        if self._last_n is not None and n_obs - self._last_n < self.refresh_every:
            return self.medoids
        self._last_n = n_obs
        points = np.asarray(x_fail, dtype=np.float64)
        if points.ndim != _POINT_NDIM or points.shape[0] < self.min_cluster_size:
            self.medoids = (
                np.empty((0, points.shape[1]), dtype=np.float64)
                if points.ndim == _POINT_NDIM
                else np.empty((0, 0), dtype=np.float64)
            )
            return self.medoids
        clusterer = HDBSCAN(min_cluster_size=self.min_cluster_size, copy=True)
        labels = clusterer.fit_predict(points)
        medoids: list[npt.NDArray[np.float64]] = []
        for label in np.unique(labels):
            if int(label) < 0:
                continue
            members = points[labels == label]
            centre = members.mean(axis=0)
            medoids.append(members[np.argmin(np.sum((members - centre) ** 2, axis=1))])
        d = points.shape[1]
        self.medoids = np.stack(medoids, axis=0) if medoids else np.empty((0, d), dtype=np.float64)
        return self.medoids


class DiversityPenalizedEV(AcquisitionFunction):
    """log EV + lambda * log(penalty + eps) (docs/07 §5.3).

    Implements: FR-SEL-003
    """

    def __init__(  # noqa: PLR0913
        self,
        model: Model,
        *,
        medoids: npt.NDArray[np.floating],
        lengthscales: npt.NDArray[np.floating],
        lambda_div: float,
        kappa_radius: float,
        noise_floor: float,
    ) -> None:
        """Wrap EV with a local-penalisation term.

        Args:
            model: Fitted GP.
            medoids: Mode centres.
            lengthscales: ARD length-scales.
            lambda_div: ``selection.probe.lambda_div``.
            kappa_radius: ``selection.probe.kappa_radius``.
            noise_floor: ``selection.gp.noise_lower_bound``.
        """
        super().__init__(model)
        self._ev = ExpectedViolation(model, noise_floor=noise_floor)
        self._medoids = np.asarray(medoids, dtype=np.float64)
        self._lengthscales = np.asarray(lengthscales, dtype=np.float64)
        self._lambda_div = lambda_div
        self._kappa_radius = kappa_radius

    def forward(self, x: Tensor) -> Tensor:
        """Evaluate the penalised log-EV acquisition.

        Args:
            x: Tensor ``b x 1 x d``.

        Returns:
            Values, shape ``b``.
        """
        log_ev = self._ev.log_forward(x)
        pts = x.squeeze(-2) if x.dim() == Q_BATCH_NDIM else x
        if self._medoids.size == 0:
            penalty = torch.ones(pts.shape[0], dtype=pts.dtype, device=pts.device)
        else:
            modes = torch.as_tensor(self._medoids, dtype=pts.dtype, device=pts.device)
            radii = self._kappa_radius * torch.as_tensor(
                self._lengthscales, dtype=pts.dtype, device=pts.device
            ).reshape(1, -1)
            delta = (pts.unsqueeze(1) - modes.unsqueeze(0)) / radii
            penalty = torch.prod(1.0 - torch.exp(-_HALF * torch.sum(delta**2, dim=-1)), dim=1)
        return log_ev + self._lambda_div * torch.log(penalty + PENALTY_FLOOR)
