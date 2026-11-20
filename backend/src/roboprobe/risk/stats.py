"""Binomial proportion helpers for risk volumes (Wilson score interval).

Implements: T-077
"""

from __future__ import annotations

import math

__all__ = ["wilson_interval"]


def wilson_interval(successes: int, n: int, *, z: float) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Args:
        successes: Number of positive outcomes (``0 … n``).
        n: Trial count (must be positive).
        z: Normal critical value (e.g. ``norm.ppf(1 - alpha/2)``).

    Returns:
        ``(low, high)`` clipped to ``[0, 1]``.
    """
    if n <= 0:
        msg = "n must be positive"
        raise ValueError(msg)
    if successes < 0 or successes > n:
        msg = "successes must lie in [0, n]"
        raise ValueError(msg)
    if z <= 0:
        msg = "z must be positive"
        raise ValueError(msg)
    phat = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = phat + z2 / (2.0 * n)
    half = z * math.sqrt(phat * (1.0 - phat) / n + z2 / (4.0 * n * n))
    low = (centre - half) / denom
    high = (centre + half) / denom
    return (max(0.0, low), min(1.0, high))
