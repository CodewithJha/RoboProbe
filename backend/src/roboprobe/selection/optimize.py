"""Acquisition optimiser wrapper and Kriging-Believer batches (docs/07 §5.5-5.7).

Integer parameters are relaxed to continuous and rounded with de-duplication.
Categorical parameters are out of scope for ``warehouse_v1`` (docs/07 §5.5).

Layer: Domain (L2).

Implements: FR-SEL-006, T-056c
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Sequence

import numpy as np
import numpy.typing as npt

from roboprobe.core.settings.selection import AcquisitionDefaults
from roboprobe.selection._compat import (
    AcquisitionFunction,
    NumericalWarning,
    Tensor,
    optimize_acqf,
    torch,
)
from roboprobe.selection.acquisition import Q_BATCH_NDIM
from roboprobe.selection.surrogate import RobustnessGP

__all__ = ["kriging_believer_batch", "optimize", "round_integers"]

MAX_TABU_TRIES: int = 3
"""Rejection retries before falling back to the best feasible raw sample (docs/07 §5.7)."""
UNIT_MIDPOINT: float = 0.5
"""Centre of the unit cube, used only as a last-resort fallback."""

AcqFactory = Callable[[RobustnessGP], AcquisitionFunction]
FeasibleFn = Callable[[npt.NDArray[np.float64]], bool]


def round_integers(
    x: npt.NDArray[np.floating],
    integer_dims: Sequence[int],
) -> npt.NDArray[np.float64]:
    """Round relaxed integer coordinates back onto the grid in ``[0, 1]``.

    Args:
        x: Point in the unit cube.
        integer_dims: Axes treated as integers.

    Returns:
        Copy of ``x`` with those axes rounded.
    """
    out = np.asarray(x, dtype=np.float64).copy()
    if not integer_dims:
        return out
    idx = list(integer_dims)
    out[..., idx] = np.clip(np.rint(out[..., idx]), 0.0, 1.0)
    return out


def optimize(  # noqa: PLR0913
    acq: AcquisitionFunction,
    *,
    d: int,
    settings: AcquisitionDefaults,
    generator: torch.Generator,
    is_feasible: FeasibleFn | None = None,
    tabu: Sequence[npt.NDArray[np.floating]] = (),
    integer_dims: Sequence[int] = (),
    existing: Sequence[npt.NDArray[np.floating]] = (),
) -> npt.NDArray[np.float64]:
    """Maximise ``acq`` on ``[0, 1]^d`` with restarts, tabu and de-duplication.

    Args:
        acq: BoTorch acquisition (q=1).
        d: Dimension.
        settings: ``selection.acq``.
        generator: Seeded CPU generator (docs/07 §5.7).
        is_feasible: Optional constraint predicate; default: all unit-cube points.
        tabu: Points already rejected.
        integer_dims: Axes to round after search.
        existing: Observed/pending/batch mates for de-duplication.

    Returns:
        A feasible point of shape ``(d,)``.
    """
    bounds = torch.stack((torch.zeros(d), torch.ones(d))).to(dtype=torch.float64)
    forbidden = [np.asarray(p, dtype=np.float64).reshape(-1) for p in (*tabu, *existing)]
    feasible = is_feasible if is_feasible is not None else _in_unit_cube

    def ok(point: npt.NDArray[np.float64]) -> bool:
        rounded = round_integers(np.clip(point, 0.0, 1.0), integer_dims)
        if not feasible(rounded):
            return False
        return all(
            float(np.max(np.abs(rounded - other))) > settings.dedupe_tol for other in forbidden
        )

    tabu_points = [np.asarray(p, dtype=np.float64).reshape(-1) for p in tabu]
    candidate: npt.NDArray[np.float64] | None = None
    for _ in range(MAX_TABU_TRIES):
        raw = _raw_samples(d, settings.raw_samples, generator)
        masked = _TabuAcquisition(acq, tabu_points, settings.dedupe_tol)
        with torch.random.fork_rng():
            torch.manual_seed(int(generator.initial_seed()))
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", NumericalWarning)
                xs, _ = optimize_acqf(
                    masked,
                    bounds=bounds,
                    q=1,
                    num_restarts=settings.num_restarts,
                    raw_samples=settings.raw_samples,
                    options={"maxiter": settings.maxiter},
                )
        point = round_integers(xs.detach().cpu().numpy().reshape(d), integer_dims)
        if ok(point):
            return point
        tabu_points.append(point)
        candidate = point
        feasible_raw = [p for p in raw if ok(p)]
        if feasible_raw:
            values = _eval_acq(acq, feasible_raw)
            return feasible_raw[int(np.argmax(values))]
    if candidate is not None and ok(candidate):
        return candidate
    raw = _raw_samples(d, settings.raw_samples, generator)
    feasible_raw = [p for p in raw if ok(p)]
    if feasible_raw:
        values = _eval_acq(acq, feasible_raw)
        return feasible_raw[int(np.argmax(values))]
    fallback = np.clip(raw[0] if len(raw) else np.full(d, UNIT_MIDPOINT), 0.0, 1.0)
    return round_integers(fallback, integer_dims)


def kriging_believer_batch(  # noqa: PLR0913
    gp: RobustnessGP,
    acq_factory: AcqFactory,
    q: int,
    *,
    settings: AcquisitionDefaults,
    generator: torch.Generator,
    is_feasible: FeasibleFn | None = None,
    integer_dims: Sequence[int] = (),
    existing: Sequence[npt.NDArray[np.floating]] = (),
) -> list[npt.NDArray[np.float64]]:
    """Greedy batch via ``condition_on_observations`` on the latent mean (docs/07 §5.6).

    Hyper-parameters are not refit. Returned points are pairwise distinct under
    ``settings.dedupe_tol`` (L-inf).

    Args:
        gp: Fitted surrogate.
        acq_factory: Builds an acquisition from the (fantasy) GP.
        q: Batch size.
        settings: ``selection.acq``.
        generator: Seeded generator.
        is_feasible: Optional constraints.
        integer_dims: Integer rounding axes.
        existing: Already chosen or pending points.

    Returns:
        ``q`` unit-cube points.
    """
    out: list[npt.NDArray[np.float64]] = []
    model_gp = gp
    known = [np.asarray(p, dtype=np.float64).reshape(-1) for p in existing]
    for _ in range(q):
        acq = acq_factory(model_gp)
        x = optimize(
            acq,
            d=gp.d,
            settings=settings,
            generator=generator,
            is_feasible=is_feasible,
            integer_dims=integer_dims,
            existing=known,
        )
        out.append(x)
        known.append(x)
        mean, _ = model_gp.predict(x.reshape(1, -1))
        model_gp = model_gp.condition_on_observations(x, mean)
    return out


class _TabuAcquisition(AcquisitionFunction):
    """Zero-out candidates within ``tol`` (L-inf) of tabu points."""

    def __init__(
        self,
        base: AcquisitionFunction,
        tabu: Sequence[npt.NDArray[np.floating]],
        tol: float,
    ) -> None:
        super().__init__(base.model)
        self._base = base
        self._tabu = [np.asarray(p, dtype=np.float64).reshape(-1) for p in tabu]
        self._tol = tol

    def forward(self, x: Tensor) -> Tensor:
        value = self._base.forward(x)
        if not self._tabu:
            return value
        pts = x.detach()
        if pts.dim() == Q_BATCH_NDIM:
            pts = pts.squeeze(-2)
        blocked = torch.zeros(pts.shape[0], dtype=torch.bool, device=pts.device)
        for point in self._tabu:
            tab = torch.as_tensor(point, dtype=pts.dtype, device=pts.device)
            blocked = blocked | (torch.max(torch.abs(pts - tab), dim=-1).values <= self._tol)
        return torch.where(blocked, torch.full_like(value, -torch.inf), value)


def _in_unit_cube(x: npt.NDArray[np.float64]) -> bool:
    return bool(np.all(x >= 0.0) and np.all(x <= 1.0))


def _raw_samples(d: int, n: int, generator: torch.Generator) -> list[npt.NDArray[np.float64]]:
    draws = torch.rand((n, d), dtype=torch.float64, generator=generator).numpy()
    return [np.asarray(row, dtype=np.float64) for row in draws]


def _eval_acq(
    acq: AcquisitionFunction, points: Sequence[npt.NDArray[np.float64]]
) -> npt.NDArray[np.float64]:
    batch = torch.as_tensor(np.stack(points), dtype=torch.float64).unsqueeze(1)
    with torch.no_grad():
        values = acq.forward(batch)
    return np.asarray(values.detach().cpu().numpy(), dtype=np.float64)
