"""Pure event-preserving trace downsampling (T-081e, FR-DSH-005)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import numpy.typing as npt

from roboprobe.core.errors import ValidationError

__all__ = ["sample_indices"]


def sample_indices(
    t: npt.NDArray[np.float64],
    clearance: npt.NDArray[np.float64],
    flags: Mapping[str, npt.NDArray[Any]],
    *,
    hz: float,
) -> npt.NDArray[np.int64]:
    """Keep each time bucket's clearance minimum, endpoints and both sides of flag flips.

    Event preservation can retain more than one sample per bucket; ``hz`` is the ordinary
    sampling target, never a reason to erase a first violation or a clearance minimum.
    """
    if not np.isfinite(hz) or hz <= 0 or t.ndim != 1 or clearance.shape != t.shape:
        msg = "invalid trace sampling inputs"
        raise ValidationError(msg)
    if not np.isfinite(t).all() or not np.isfinite(clearance).all() or np.any(np.diff(t) <= 0):
        msg = "trace times must increase and trace clearance must be finite"
        raise ValidationError(msg)
    if not len(t):
        return np.asarray([], dtype=np.int64)
    buckets = np.floor((t - t[0]) * hz)
    starts = np.r_[0, np.flatnonzero(np.diff(buckets)) + 1]
    stops = np.r_[starts[1:], len(t)]
    keep = [0, len(t) - 1]
    keep.extend(
        int(start + np.argmin(clearance[start:stop]))
        for start, stop in zip(starts, stops, strict=True)
    )
    for values in flags.values():
        if values.shape != t.shape:
            msg = "trace columns must have equal lengths"
            raise ValidationError(msg)
        flips = np.flatnonzero(values[1:] != values[:-1]) + 1
        keep.extend(int(index) for index in flips)
        keep.extend(int(index - 1) for index in flips)
    return np.unique(np.asarray(keep, dtype=np.int64))
