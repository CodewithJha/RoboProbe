"""Unit-cube samplers for baselines, warm-up and QMC integration (docs/05 §3, docs/07 §3).

Every sampler draws ``(n, d)`` points in ``[0, 1]^d``. Decode them with
:meth:`ScenarioSpace.from_unit` (docs/06 §4.1). All randomness comes from the ``numpy`` Generator
the caller injects; nothing uses a global RNG.

**Priors versus scale** (:class:`PriorSampler`). A prior is a distribution over *parameter values*
``x``, and the scale only decides how ``x`` maps to ``u``. The sampler draws ``v ~ U(0, 1)``, takes
``x = F⁻¹(v)`` and returns the scale-aware encoding of ``x``. So ``loguniform`` on a ``log``
parameter (P3 illuminance) is uniform in ``u``, while ``uniform`` on a ``log`` parameter piles up
near ``u = 1``. Integer parameters treat value ``k`` as the interval ``[k - 0.5, k + 0.5)``,
matching the bin-centre encoding, so a continuous prior gives each integer the mass of its
interval. ``discrete`` weights pick a level (int value or categorical choice), and the point lands
inside that level's bin.

Implements: FR-SEL-001 (baseline samplers)
"""

from __future__ import annotations

import itertools
import math
import warnings
from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal, Protocol

import numpy as np
import numpy.typing as npt
from scipy import stats
from scipy.stats import qmc

from roboprobe.core import errors
from roboprobe.core.types import ParamType

if TYPE_CHECKING:
    from roboprobe.scenario.space import ParameterSpec

__all__ = [
    "GridSampler",
    "LatinHypercubeSampler",
    "PriorSampler",
    "Sampler",
    "SobolSampler",
    "UniformSampler",
]

FloatArray = npt.NDArray[np.float64]
_INT_HALF_WIDTH = 0.5
_MIN_GRID_LEVELS = 2
_SEED_BOUND = 2**63
_SOBOL_BALANCE_WARNING = r".*balance properties of Sobol' points require n to be a power of 2.*"


class Sampler(Protocol):
    """Draws ``(n, d)`` points in the unit cube (docs/05 §3)."""

    def sample(self, n: int, rng: np.random.Generator) -> FloatArray:
        """Draw ``n`` points of dimension ``d``."""
        ...


def _check_dim(dim: int) -> None:
    if dim < 1:
        msg = f"sampler dimension must be >= 1, got {dim}"
        raise errors.ValidationError(msg, context={"dim": dim})


def _check_n(n: int) -> None:
    if n < 0:
        msg = f"cannot draw a negative number of points ({n})"
        raise errors.ValidationError(msg, context={"n": n})


class UniformSampler:
    """i.i.d. ``U[0, 1]^d`` points (S-RANDOM without priors)."""

    def __init__(self, dim: int) -> None:
        """Create a sampler for ``dim`` dimensions."""
        _check_dim(dim)
        self.dim = dim

    def sample(self, n: int, rng: np.random.Generator) -> FloatArray:
        """Draw ``n`` independent uniform points."""
        _check_n(n)
        return rng.random((n, self.dim))


class PriorSampler:
    """i.i.d. points whose decoded values follow each parameter's prior (S-RANDOM, docs/07 §3)."""

    def __init__(self, params: Sequence[ParameterSpec]) -> None:
        """Create a sampler over ``params`` (``ScenarioSpace.params``, in order)."""
        _check_dim(len(params))
        self.params = tuple(params)
        self.dim = len(self.params)

    def sample(self, n: int, rng: np.random.Generator) -> FloatArray:
        """Draw ``n`` points; column ``j`` is the prior inverse-CDF of parameter ``j``."""
        _check_n(n)
        v = rng.random((n, self.dim))
        columns = [_prior_to_unit(spec, v[:, j]) for j, spec in enumerate(self.params)]
        return np.clip(np.column_stack(columns), 0.0, 1.0) if n else np.empty((0, self.dim))


def _prior_to_unit(spec: ParameterSpec, v: FloatArray) -> FloatArray:
    """Map uniform ``v`` to unit coordinates whose decoded values follow ``spec.prior``."""
    prior = spec.prior
    if spec.type is ParamType.CATEGORICAL or prior.kind == "discrete":
        levels = len(spec.choices or ()) or int((spec.high or 0) - (spec.low or 0)) + 1
        weights = np.asarray(prior.weights or np.ones(levels), dtype=np.float64)
        return _discrete_to_unit(weights, v)
    low, high = float(spec.low or 0), float(spec.high or 0)
    lo, hi = (
        (low - _INT_HALF_WIDTH, high + _INT_HALF_WIDTH)
        if spec.type is ParamType.INT
        else (low, high)
    )
    x = _inverse_cdf(spec, lo, hi, v)
    if spec.type is ParamType.INT:
        return (x - lo) / (hi - lo)
    if spec.scale == "log":
        return (np.log(x) - math.log(low)) / (math.log(high) - math.log(low))
    return (x - low) / (high - low)


def _inverse_cdf(spec: ParameterSpec, lo: float, hi: float, v: FloatArray) -> FloatArray:
    prior = spec.prior
    if prior.kind == "loguniform":
        return np.exp(math.log(lo) + v * (math.log(hi) - math.log(lo)))
    if prior.kind == "truncnormal":
        mean, std = float(prior.mean or 0), float(prior.std or 1)
        dist = stats.truncnorm((lo - mean) / std, (hi - mean) / std, loc=mean, scale=std)
        return np.asarray(dist.ppf(v), dtype=np.float64)
    if prior.kind == "beta":
        beta = stats.beta(float(prior.a or 1), float(prior.b or 1))
        return lo + np.asarray(beta.ppf(v), dtype=np.float64) * (hi - lo)
    return lo + v * (hi - lo)


def _discrete_to_unit(weights: FloatArray, v: FloatArray) -> FloatArray:
    """Pick level ``i`` with probability ``w_i / Σw`` and place the point inside bin ``i``."""
    cdf = np.concatenate(([0.0], np.cumsum(weights) / weights.sum()))
    index = np.clip(np.searchsorted(cdf, v, side="right") - 1, 0, len(weights) - 1)
    # side="right" skips zero-weight levels (zero-width CDF steps) because v < 1.
    width = cdf[index + 1] - cdf[index]
    within = np.divide(v - cdf[index], width, out=np.full_like(v, 0.5), where=width > 0)
    unit: FloatArray = (index + np.clip(within, 0.0, 1.0)) / len(weights)
    return unit


class LatinHypercubeSampler:
    """Latin hypercube designs, one point per stratum per dimension (S-LHS, docs/07 §3).

    Every call returns a fresh ``n``-point design (``scipy.stats.qmc.LatinHypercube``). S-LHS draws
    the whole budget once at campaign start and consumes it in order.
    """

    def __init__(
        self, dim: int, *, optimization: Literal["random-cd", "lloyd"] | None = "random-cd"
    ) -> None:
        """Create a sampler; ``optimization`` is passed to SciPy (docs/07 §3 uses ``random-cd``)."""
        _check_dim(dim)
        self.dim = dim
        self.optimization = optimization

    def sample(self, n: int, rng: np.random.Generator) -> FloatArray:
        """Draw an ``n``-point Latin hypercube."""
        _check_n(n)
        if n == 0:
            return np.empty((0, self.dim))
        engine = qmc.LatinHypercube(self.dim, optimization=self.optimization, rng=rng)
        return np.asarray(engine.random(n), dtype=np.float64)


class SobolSampler:
    """Scrambled Sobol' sequence, consumed in order across calls (S-SOBOL, docs/07 §3).

    The engine is seeded once, from ``seed`` or from the first ``rng`` passed to :meth:`sample`.
    After that, later calls continue the same sequence and ignore ``rng``. Prefixes of size
    ``2^m`` have the balance property; SciPy's power-of-two warning is suppressed because
    strategies consume arbitrary batch sizes. To resume, persist :attr:`seed` and
    :attr:`position`, then call ``SobolSampler(d, seed=seed).fast_forward(position)``.
    """

    def __init__(self, dim: int, *, seed: int | None = None) -> None:
        """Create a sampler; ``seed`` fixes the scrambling (else derived from the first ``rng``)."""
        _check_dim(dim)
        self.dim = dim
        self._seed = seed
        self._engine: qmc.Sobol | None = None
        self._position = 0

    @property
    def seed(self) -> int | None:
        """Scrambling seed; ``None`` until the first draw if none was given."""
        return self._seed

    @property
    def position(self) -> int:
        """Number of points consumed so far."""
        return self._position

    def _ensure_engine(self, rng: np.random.Generator | None) -> qmc.Sobol:
        if self._engine is None:
            if self._seed is None:
                if rng is None:
                    msg = "SobolSampler needs a seed or an rng before its first use"
                    raise errors.ValidationError(msg)
                self._seed = int(rng.integers(_SEED_BOUND))
            self._engine = qmc.Sobol(self.dim, scramble=True, rng=np.random.default_rng(self._seed))
        return self._engine

    def sample(self, n: int, rng: np.random.Generator) -> FloatArray:
        """Return the next ``n`` points of the sequence."""
        _check_n(n)
        engine = self._ensure_engine(rng)
        if n == 0:
            return np.empty((0, self.dim))
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=_SOBOL_BALANCE_WARNING, category=UserWarning)
            points = np.asarray(engine.random(n), dtype=np.float64)
        self._position += n
        return points

    def fast_forward(self, n: int, rng: np.random.Generator | None = None) -> SobolSampler:
        """Skip ``n`` points (to resume a stored position); returns ``self``."""
        _check_n(n)
        self._ensure_engine(rng).fast_forward(n)
        self._position += n
        return self


class GridSampler:
    """Full factorial grid, ``levels`` points per dimension at ``{0, 1/(k-1), ..., 1}`` (S-GRID).

    The grid has ``levels ** dim`` points in lexicographic order: the first dimension varies
    slowest and the last fastest, as in ``itertools.product``. :meth:`sample` returns the whole grid
    in that order when ``n`` equals its size. A smaller ``n`` takes the first ``n`` points of an
    ``rng`` permutation, as docs/07 §3 specifies when ``k^d`` exceeds the budget.
    """

    def __init__(self, dim: int, levels: int) -> None:
        """Create a grid sampler (``levels >= 2``)."""
        _check_dim(dim)
        if levels < _MIN_GRID_LEVELS:
            msg = f"grid needs >= {_MIN_GRID_LEVELS} levels per dimension, got {levels}"
            raise errors.ValidationError(msg, context={"levels": levels})
        self.dim = dim
        self.levels = levels

    @classmethod
    def for_budget(cls, dim: int, budget: int) -> GridSampler:
        """Grid with ``k = max(2, floor(budget ** (1/dim)))`` levels (docs/07 §3)."""
        _check_dim(dim)
        k = max(_MIN_GRID_LEVELS, math.floor(max(budget, 1) ** (1 / dim)))
        while (k + 1) ** dim <= budget:  # guard against floating-point roots rounding down
            k += 1
        while k > _MIN_GRID_LEVELS and k**dim > budget:
            k -= 1
        return cls(dim, k)

    @property
    def size(self) -> int:
        """Number of grid points, ``levels ** dim``."""
        return int(self.levels**self.dim)

    def points(self) -> FloatArray:
        """All grid points in lexicographic order, shape ``(levels ** dim, dim)``."""
        axis = np.linspace(0.0, 1.0, self.levels)
        return np.array(list(itertools.product(axis, repeat=self.dim)), dtype=np.float64)

    def sample(self, n: int, rng: np.random.Generator) -> FloatArray:
        """Return ``n`` distinct grid points (see the class docstring for the order).

        Raises:
            roboprobe.core.errors.ValidationError: If ``n`` exceeds :attr:`size`.
        """
        _check_n(n)
        if n > self.size:
            msg = f"grid has {self.size} points, cannot draw {n}"
            raise errors.ValidationError(msg, context={"n": n, "size": self.size})
        grid = self.points()
        if n == self.size:
            return grid
        return grid[rng.permutation(self.size)[:n]]
