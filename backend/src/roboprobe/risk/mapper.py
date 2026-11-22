"""Pairwise risk slices and region classification (docs/05 §8, docs/09 §5).

Implements: T-076, FR-RSK-001, FR-RSK-002, FR-RSK-003, PR-07
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Protocol

import numpy as np
import numpy.typing as npt
from scipy.stats import norm

from roboprobe.core.errors import ValidationError
from roboprobe.core.settings.analysis import RiskSettings, RiskThresholds
from roboprobe.scenario.space import ScenarioSpace

__all__ = [
    "REGION_FAILURE",
    "REGION_SAFE",
    "REGION_UNCERTAIN",
    "RiskMapper",
    "RiskSlice",
    "load_slices",
    "save_slices",
]

REGION_SAFE = np.int8(0)
REGION_UNCERTAIN = np.int8(1)
REGION_FAILURE = np.int8(2)

_DEFAULT_RESOLUTION = int(RiskSettings.model_fields["slice_resolution"].default)
_STD_FLOOR = 1e-12
_MIN_FREE_DIM = 2
_MIN_RESOLUTION = 2


class _GpPort(Protocol):
    """Minimal GP surface used by :class:`RiskMapper` (matches :class:`RobustnessGP`)."""

    def predict(
        self, x: npt.NDArray[np.floating]
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]: ...

    def predict_total_std(self, x: npt.NDArray[np.floating]) -> npt.NDArray[np.float64]: ...


@dataclass(frozen=True, slots=True)
class RiskSlice:
    """One 2-D risk atlas slice (docs/09 §5.3)."""

    x_param: str
    y_param: str
    x_values: npt.NDArray[np.float64]
    y_values: npt.NDArray[np.float64]
    log_x: bool
    log_y: bool
    p_fail: npt.NDArray[np.float64]
    mean: npt.NDArray[np.float64]
    std: npt.NDArray[np.float64]
    region: npt.NDArray[np.int8]
    anchor: Mapping[str, Any]
    grid_u: npt.NDArray[np.float64]


class RiskMapper:
    """Operating-envelope risk atlas from a robustness GP (docs/05 §8)."""

    def __init__(
        self,
        gp: _GpPort,
        space: ScenarioSpace,
        thresholds: RiskThresholds,
    ) -> None:
        """Bind a fitted robustness GP, scenario space and region thresholds."""
        self._gp = gp
        self._space = space
        self._thresholds = thresholds
        if space.dim < _MIN_FREE_DIM:
            msg = "RiskMapper requires a space with at least two free parameters"
            raise ValidationError(msg, context={"dim": space.dim})

    @property
    def space(self) -> ScenarioSpace:
        """Scenario space the mapper was constructed with."""
        return self._space

    @property
    def thresholds(self) -> RiskThresholds:
        """Region cut-offs used by :meth:`classify`."""
        return self._thresholds

    def slice(
        self,
        x_param: str,
        y_param: str,
        anchor: Mapping[str, Any],
        resolution: int = _DEFAULT_RESOLUTION,
    ) -> RiskSlice:
        """Evaluate one pairwise slice on a ``resolution x resolution`` unit grid."""
        if resolution < _MIN_RESOLUTION:
            msg = "slice resolution must be at least 2"
            raise ValidationError(msg, context={"resolution": resolution})
        if x_param == y_param:
            msg = "slice axes must be distinct"
            raise ValidationError(msg, context={"x_param": x_param, "y_param": y_param})
        ids = {p.id for p in self._space.params}
        if x_param not in ids or y_param not in ids:
            msg = "slice parameter is not free in the space"
            raise ValidationError(
                msg,
                context={
                    "x_param": x_param,
                    "y_param": y_param,
                    "free": ",".join(sorted(ids)),
                },
            )
        slices = self._evaluate_pairs([(x_param, y_param)], anchor, resolution)
        return slices[0]

    def all_pair_slices(
        self,
        anchor: Mapping[str, Any],
        resolution: int = _DEFAULT_RESOLUTION,
    ) -> list[RiskSlice]:
        """Every unordered free-parameter pair, one batched GP call."""
        if resolution < _MIN_RESOLUTION:
            msg = "slice resolution must be at least 2"
            raise ValidationError(msg, context={"resolution": resolution})
        pairs = list(itertools.combinations([p.id for p in self._space.params], 2))
        return self._evaluate_pairs(pairs, anchor, resolution)

    def classify(self, x_unit: npt.NDArray[np.floating]) -> npt.NDArray[np.int8]:
        """Region codes ``0`` SAFE / ``1`` UNCERTAIN / ``2`` FAILURE for unit-cube rows."""
        points = np.asarray(x_unit, dtype=np.float64)
        if points.ndim == 1:
            points = points.reshape(1, -1)
        p_fail = self._p_fail(points)
        return _regions(p_fail, self._thresholds)

    def _evaluate_pairs(
        self,
        pairs: Sequence[tuple[str, str]],
        anchor: Mapping[str, Any],
        resolution: int,
    ) -> list[RiskSlice]:
        axis = np.linspace(0.0, 1.0, resolution, dtype=np.float64)
        n_pair = len(pairs)
        n_cell = resolution * resolution
        x_all = np.empty((n_pair * n_cell, self._space.dim), dtype=np.float64)
        base = self._anchor_unit(anchor)
        idx = {p.id: i for i, p in enumerate(self._space.params)}
        for p_i, (x_id, y_id) in enumerate(pairs):
            gx, gy = np.meshgrid(axis, axis, indexing="xy")
            block = np.broadcast_to(base, (n_cell, self._space.dim)).copy()
            block[:, idx[x_id]] = gx.ravel()
            block[:, idx[y_id]] = gy.ravel()
            start = p_i * n_cell
            x_all[start : start + n_cell] = block

        mean, std_latent = self._gp.predict(x_all)
        std_tot = self._gp.predict_total_std(x_all)
        p_fail = _phi_neg(mean, std_tot)
        regions = _regions(p_fail, self._thresholds)

        out: list[RiskSlice] = []
        frozen_anchor = dict(anchor)
        for p_i, (x_id, y_id) in enumerate(pairs):
            start = p_i * n_cell
            end = start + n_cell
            shape = (resolution, resolution)
            grid_u = x_all[start:end].reshape(resolution, resolution, self._space.dim)
            x_values = self._axis_physical(x_id, axis, base, idx)
            y_values = self._axis_physical(y_id, axis, base, idx)
            out.append(
                RiskSlice(
                    x_param=x_id,
                    y_param=y_id,
                    x_values=x_values,
                    y_values=y_values,
                    log_x=self._space.param(x_id).scale == "log",
                    log_y=self._space.param(y_id).scale == "log",
                    p_fail=p_fail[start:end].reshape(shape),
                    mean=mean[start:end].reshape(shape),
                    std=std_latent[start:end].reshape(shape),
                    region=regions[start:end].reshape(shape),
                    anchor=frozen_anchor,
                    grid_u=grid_u,
                )
            )
        return out

    def _anchor_unit(self, anchor: Mapping[str, Any]) -> npt.NDArray[np.float64]:
        values = dict(self._space.nominal_values())
        values.update(dict(anchor))
        # Pins already removed from free params; ensure free keys present.
        return np.asarray(self._space.to_unit(values), dtype=np.float64)

    def _axis_physical(
        self,
        param_id: str,
        axis_u: npt.NDArray[np.float64],
        base: npt.NDArray[np.float64],
        idx: Mapping[str, int],
    ) -> npt.NDArray[np.float64]:
        rows = np.broadcast_to(base, (axis_u.size, self._space.dim)).copy()
        rows[:, idx[param_id]] = axis_u
        decoded = self._space.from_unit_batch(rows)
        return np.asarray([float(row[param_id]) for row in decoded], dtype=np.float64)

    def _p_fail(self, x: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        mean, _ = self._gp.predict(x)
        std_tot = self._gp.predict_total_std(x)
        return _phi_neg(mean, std_tot)


def _phi_neg(
    mean: npt.NDArray[np.float64], std: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    safe = np.maximum(np.asarray(std, dtype=np.float64), _STD_FLOOR)
    return np.asarray(norm.cdf(-np.asarray(mean, dtype=np.float64) / safe), dtype=np.float64)


def _regions(p_fail: npt.NDArray[np.float64], thresholds: RiskThresholds) -> npt.NDArray[np.int8]:
    out = np.full(p_fail.shape, REGION_UNCERTAIN, dtype=np.int8)
    out[p_fail < thresholds.safe] = REGION_SAFE
    out[p_fail > thresholds.failure] = REGION_FAILURE
    return out


def save_slices(path: Path, slices: Sequence[RiskSlice]) -> None:
    """Write ``slices`` to a compressed ``.npz`` (T-076)."""
    meta = [
        {
            "x_param": item.x_param,
            "y_param": item.y_param,
            "log_x": item.log_x,
            "log_y": item.log_y,
            "anchor": dict(item.anchor),
        }
        for item in slices
    ]
    payload: dict[str, Any] = {"meta": np.asarray(json.dumps(meta))}
    for i, item in enumerate(slices):
        payload[f"{i}_x_values"] = item.x_values
        payload[f"{i}_y_values"] = item.y_values
        payload[f"{i}_p_fail"] = item.p_fail
        payload[f"{i}_mean"] = item.mean
        payload[f"{i}_std"] = item.std
        payload[f"{i}_region"] = item.region
        payload[f"{i}_grid_u"] = item.grid_u
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **payload)


def load_slices(path: Path | BinaryIO) -> list[RiskSlice]:
    """Load slices previously written by :func:`save_slices`."""
    with np.load(path, allow_pickle=False) as data:
        meta = json.loads(str(data["meta"]))
        out: list[RiskSlice] = []
        for i, entry in enumerate(meta):
            out.append(
                RiskSlice(
                    x_param=str(entry["x_param"]),
                    y_param=str(entry["y_param"]),
                    x_values=np.asarray(data[f"{i}_x_values"], dtype=np.float64),
                    y_values=np.asarray(data[f"{i}_y_values"], dtype=np.float64),
                    log_x=bool(entry["log_x"]),
                    log_y=bool(entry["log_y"]),
                    p_fail=np.asarray(data[f"{i}_p_fail"], dtype=np.float64),
                    mean=np.asarray(data[f"{i}_mean"], dtype=np.float64),
                    std=np.asarray(data[f"{i}_std"], dtype=np.float64),
                    region=np.asarray(data[f"{i}_region"], dtype=np.int8),
                    anchor=dict(entry["anchor"]),
                    grid_u=np.asarray(data[f"{i}_grid_u"], dtype=np.float64),
                )
            )
        return out
