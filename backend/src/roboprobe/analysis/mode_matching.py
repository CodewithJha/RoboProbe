"""Stable mode identity via Hungarian matching on Jaccard overlap (docs/05 §7).

Implements: FR-ANA-002, FR-ANA-006
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import numpy as np
from scipy.optimize import linear_sum_assignment

from roboprobe.analysis.types import FailureModeSummary, ModeMatch, StoredMode

__all__ = ["match_modes"]

_CODE_WIDTH = 2
_CODE_PREFIX = "FM-"


def match_modes(
    previous: Sequence[StoredMode],
    new: Sequence[FailureModeSummary],
    threshold: float,
) -> ModeMatch:
    """Assign new clusters to stored modes when Jaccard ≥ ``threshold``.

    Implements: FR-ANA-002

    Cost is ``1 - J``. Inputs are ordered by the smallest member UUID so ties are stable.
    Unmatched stored modes are listed as ``stale_ids``; their codes are never reused.
    """
    prev = sorted(previous, key=lambda m: (min(m.member_run_ids, default=UUID(int=0)), m.code))
    new_order = sorted(
        range(len(new)),
        key=lambda i: (min(new[i].member_run_ids, default=UUID(int=0)), i),
    )
    n_new, n_prev = len(new), len(prev)
    assignments: dict[int, UUID] = {}
    preserved: dict[int, str] = {}
    matched_prev: set[int] = set()
    if n_new and n_prev:
        cost = np.ones((n_new, n_prev), dtype=np.float64)
        for row, ni in enumerate(new_order):
            a = set(new[ni].member_run_ids)
            for col, stored in enumerate(prev):
                cost[row, col] = 1.0 - _jaccard(a, stored.member_run_ids)
        rows, cols = linear_sum_assignment(cost)
        for row_i, col_i in zip(rows, cols, strict=True):
            row, col = int(row_i), int(col_i)
            jaccard = 1.0 - float(cost[row, col])
            if jaccard >= threshold:
                ni = new_order[row]
                assignments[ni] = prev[col].id
                matched_prev.add(col)
                if prev[col].label_is_user:
                    preserved[ni] = prev[col].label
    used = {_code_number(m.code) for m in previous}
    next_code = (max(used) if used else 0) + 1
    new_codes: dict[int, str] = {}
    for i in range(n_new):
        if i in assignments:
            stored = next(m for m in previous if m.id == assignments[i])
            new_codes[i] = stored.code
        else:
            new_codes[i] = _format_code(next_code)
            next_code += 1
    stale = tuple(prev[i].id for i in range(n_prev) if i not in matched_prev)
    return ModeMatch(
        assignments=assignments,
        new_codes=new_codes,
        preserved_labels=preserved,
        stale_ids=stale,
    )


def _jaccard(a: set[UUID], b: frozenset[UUID]) -> float:
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _code_number(code: str) -> int:
    if code.startswith(_CODE_PREFIX):
        try:
            return int(code[len(_CODE_PREFIX) :])
        except ValueError:
            return 0
    return 0


def _format_code(n: int) -> str:
    return f"{_CODE_PREFIX}{n:0{_CODE_WIDTH}d}"
