"""Planted-parameter datasets shared by importance and rule tests (T-072, T-073)."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt


def planted_xor(
    n: int, d: int, seed: int, *, threshold: float = 0.6
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.bool_], list[str]]:
    """FAIL iff ``x0 > threshold`` AND ``x1 > threshold`` (planted pair)."""
    rng = np.random.Generator(np.random.PCG64(seed))
    x = rng.random((n, d))
    y = (x[:, 0] > threshold) & (x[:, 1] > threshold)
    names = [f"p{i}" for i in range(d)]
    return x, y, names


def planted_threshold(
    n: int, d: int, seed: int, *, cut: float = 0.4
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.bool_], list[str]]:
    """FAIL iff ``x0 > cut``."""
    rng = np.random.Generator(np.random.PCG64(seed))
    x = rng.random((n, d))
    y = x[:, 0] > cut
    names = [f"p{i}" for i in range(d)]
    return x, y, names
