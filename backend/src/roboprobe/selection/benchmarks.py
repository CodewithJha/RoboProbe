"""Analytic benchmark robustness functions for fast selector tests (docs/07 §9).

Implements: FR-SEL-002, FR-SEL-003
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike

__all__ = [
    "MODE_CANONICAL",
    "NOMINAL_POINT",
    "ModeLabel",
    "branin_falsify",
    "label_mode",
    "multi_mode_6d",
]

ModeLabel = Literal["A", "B", "C", "D"]

# Branin (Forrester et al.) constants — mathematical definition, not tunables.
_BRANIN_A = 1.0
_BRANIN_B = 5.1 / (4.0 * math.pi**2)
_BRANIN_C = 5.0 / math.pi
_BRANIN_R = 6.0
_BRANIN_S = 10.0
_BRANIN_T = 1.0 / (8.0 * math.pi)
_BRANIN_X1_SCALE = 15.0
_BRANIN_X1_SHIFT = -5.0
_BRANIN_X2_SCALE = 15.0
_BRANIN_OFFSET = 1.5
_BRANIN_DIV = 50.0

# multi_mode_6d soft-threshold definition (docs/07 §9). Thresholds calibrated so
# noise-free failure volume ≈ 0.7 % of the unit cube under Sobol QMC.
_SIGMOID_SCALE = 0.03
_RHO_OFFSET = 0.3
_RHO_GAIN = 0.6
_A_U1 = 0.86
_A_U3 = 0.07
_A_U4 = 0.81
_B_U5 = 0.045
_B_U6 = 0.93
_C_U2 = 0.018
_C_U1 = 0.86
_D_U4 = 0.996
_DEFAULT_NOISE = 0.02
_UNIT_DIM_BRANIN = 2
_UNIT_DIM_MULTI = 6

MODE_CANONICAL: dict[ModeLabel, tuple[float, ...]] = {
    "A": (1.0, 0.5, 0.0, 0.9, 0.5, 0.5),
    "B": (0.5, 0.5, 0.5, 0.5, 0.0, 1.0),
    "C": (1.0, 0.0, 0.5, 0.5, 0.5, 0.5),
    "D": (0.5, 0.5, 0.5, 1.0, 0.5, 0.5),
}
"""Unit-cube points deep inside each GT mode (noise-free rho < 0)."""

NOMINAL_POINT: tuple[float, ...] = (0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
"""Noise-free nominal (passes: rho > 0)."""


def branin_falsify(u: ArrayLike) -> float:
    """Falsification Branin: rho < 0 near the three classic minima (docs/07 §9).

    Maps unit ``u in [0, 1]^2`` to Branin inputs ``(15u0-5, 15u1)``, then
    ``rho = clip((branin - 1.5) / 50, -1, 1)``.
    """
    vec = _as_unit_vector(u, _UNIT_DIM_BRANIN)
    x1 = _BRANIN_X1_SCALE * float(vec[0]) + _BRANIN_X1_SHIFT
    x2 = _BRANIN_X2_SCALE * float(vec[1])
    branin = (
        _BRANIN_A * (x2 - _BRANIN_B * x1**2 + _BRANIN_C * x1 - _BRANIN_R) ** 2
        + _BRANIN_S * (1.0 - _BRANIN_T) * math.cos(x1)
        + _BRANIN_S
    )
    return float(np.clip((branin - _BRANIN_OFFSET) / _BRANIN_DIV, -1.0, 1.0))


def multi_mode_6d(
    u: ArrayLike,
    noise: float = _DEFAULT_NOISE,
    *,
    rng: np.random.Generator | None = None,
) -> float:
    """Six-dimensional multi-mode robustness mirror of kinematic2d GT (docs/07 §9).

    Args:
        u: Unit-cube vector of length 6.
        noise: Gaussian observation noise std (default 0.02).
        rng: Injected generator for the noise term; required when ``noise > 0``.
    """
    if noise < 0.0:
        msg = "noise must be non-negative"
        raise ValueError(msg)
    terms = _mode_terms(_as_unit_vector(u, _UNIT_DIM_MULTI))
    rho = float(np.min(terms))
    if noise > 0.0:
        if rng is None:
            msg = "rng is required when noise > 0"
            raise ValueError(msg)
        rho = rho + float(rng.normal(0.0, noise))
    return float(np.clip(rho, -1.0, 1.0))


def label_mode(u: ArrayLike) -> ModeLabel | None:
    """Return the active GT mode letter, or ``None`` when noise-free rho >= 0.

    The active mode is the argmin of the four soft terms (A, B, C, D).
    """
    terms = _mode_terms(_as_unit_vector(u, _UNIT_DIM_MULTI))
    if float(np.min(terms)) >= 0.0:
        return None
    index = int(np.argmin(terms))
    labels: tuple[ModeLabel, ...] = ("A", "B", "C", "D")
    return labels[index]


def _mode_terms(u: np.ndarray) -> np.ndarray:
    """Noise-free soft terms ``0.3 - 0.6 * activation`` for modes A-D."""
    a = _sigmoid(u[0] - _A_U1) * _sigmoid(_A_U3 - u[2]) * _sigmoid(u[3] - _A_U4)
    b = _sigmoid(_B_U5 - u[4]) * _sigmoid(u[5] - _B_U6)
    c = _sigmoid(_C_U2 - u[1]) * _sigmoid(u[0] - _C_U1)
    d = _sigmoid(u[3] - _D_U4)
    activations = np.asarray([a, b, c, d], dtype=np.float64)
    return _RHO_OFFSET - _RHO_GAIN * activations


def _sigmoid(z: float) -> float:
    return float(1.0 / (1.0 + math.exp(-z / _SIGMOID_SCALE)))


def _as_unit_vector(u: ArrayLike, dim: int) -> np.ndarray:
    vec = np.asarray(u, dtype=np.float64).reshape(-1)
    if vec.shape[0] != dim:
        msg = f"expected unit vector of length {dim}, got {vec.shape[0]}"
        raise ValueError(msg)
    if np.any(vec < 0.0) or np.any(vec > 1.0):
        msg = "unit vector components must lie in [0, 1]"
        raise ValueError(msg)
    return vec
