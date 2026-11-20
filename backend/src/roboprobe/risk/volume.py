"""Sobol QMC region volumes and robustness score (docs/05 §8, docs/09 §5.4).

Implements: T-077, FR-RSK-004, FR-RSK-005, PR-17
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import norm, qmc

from roboprobe.core.errors import ValidationError
from roboprobe.core.settings.analysis import RiskSettings
from roboprobe.core.settings.experiments import ExperimentSettings
from roboprobe.risk.mapper import REGION_FAILURE, REGION_SAFE, REGION_UNCERTAIN, RiskMapper
from roboprobe.risk.stats import wilson_interval

__all__ = ["RegionVolumes", "VolumeEstimator", "robustness_score"]

_DEFAULT_N = int(RiskSettings.model_fields["volume_samples"].default)
_DEFAULT_ALPHA = float(ExperimentSettings.model_fields["alpha"].default)
_UNCERTAIN_WEIGHT = 0.5
_FRACTION_SUM_ATOL = 1e-12


@dataclass(frozen=True, slots=True)
class RegionVolumes:
    """SAFE / UNCERTAIN / FAILURE volume fractions with Wilson intervals."""

    safe: float
    uncertain: float
    failure: float
    safe_ci: tuple[float, float]
    uncertain_ci: tuple[float, float]
    failure_ci: tuple[float, float]
    n: int
    seed: int


class VolumeEstimator:
    """Estimate region volumes via scrambled Sobol QMC (docs/09 §5.4)."""

    def __init__(self, *, alpha: float = _DEFAULT_ALPHA) -> None:
        """Configure the Wilson critical value from significance ``alpha``."""
        if not 0.0 < alpha < 1.0:
            msg = "alpha must be in (0, 1)"
            raise ValidationError(msg, context={"alpha": alpha})
        self._z = float(norm.ppf(1.0 - alpha / 2.0))
        self._alpha = alpha

    def estimate(
        self,
        mapper: RiskMapper,
        n: int = _DEFAULT_N,
        seed: int = 0,
    ) -> RegionVolumes:
        """Classify ``n`` Sobol points on ``mapper.space`` (pins already removed)."""
        if n <= 0 or (n & (n - 1)) != 0:
            msg = "n must be a positive power of two"
            raise ValidationError(msg, context={"n": n})
        dim = mapper.space.dim
        engine = qmc.Sobol(d=dim, scramble=True, seed=seed)
        points = np.asarray(engine.random(n), dtype=np.float64)
        regions = mapper.classify(points)
        n_safe = int(np.sum(regions == REGION_SAFE))
        n_unc = int(np.sum(regions == REGION_UNCERTAIN))
        n_fail = int(np.sum(regions == REGION_FAILURE))
        if n_safe + n_unc + n_fail != n:
            msg = "region codes must cover every sample"
            raise ValidationError(
                msg,
                context={"n_safe": n_safe, "n_uncertain": n_unc, "n_failure": n_fail, "n": n},
            )
        safe = n_safe / n
        uncertain = n_unc / n
        failure = n_fail / n
        return RegionVolumes(
            safe=safe,
            uncertain=uncertain,
            failure=failure,
            safe_ci=wilson_interval(n_safe, n, z=self._z),
            uncertain_ci=wilson_interval(n_unc, n, z=self._z),
            failure_ci=wilson_interval(n_fail, n, z=self._z),
            n=n,
            seed=seed,
        )


def robustness_score(vol: RegionVolumes) -> float:
    """Campaign-level score ``1 - f_FAILURE - 0.5 * f_UNCERTAIN`` in ``[0, 1]``.

    This is not the per-run robustness bar on the dashboard (that shows episode ``rho``).
    """
    total = vol.safe + vol.uncertain + vol.failure
    if abs(total - 1.0) > _FRACTION_SUM_ATOL:
        msg = "region fractions must sum to 1"
        raise ValidationError(
            msg,
            context={"safe": vol.safe, "uncertain": vol.uncertain, "failure": vol.failure},
        )
    score = 1.0 - vol.failure - _UNCERTAIN_WEIGHT * vol.uncertain
    return float(min(1.0, max(0.0, score)))
