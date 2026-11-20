"""Depth-limited decision tree → physical-unit FAIL rules (docs/09 §4.3).

Implements: FR-ANA-004
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal
from uuid import UUID

import numpy as np
import numpy.typing as npt
from sklearn.tree import DecisionTreeClassifier  # type: ignore[import-untyped]

from roboprobe.analysis._const import MATRIX_NDIM, N_CLASSES_BINARY
from roboprobe.analysis.modes import denormalize_param
from roboprobe.analysis.settings import LabelLexicon, RuleExtractorSettings
from roboprobe.analysis.types import Condition, FailureModeSummary, Rule
from roboprobe.core.types import FailureClass
from roboprobe.scenario.space import ScenarioSpace

__all__ = ["RuleExtractor", "render_rule"]

_LEFT: Literal["<"] = "<"
_RIGHT: Literal["≥"] = "≥"
_FAIL = 1
_DISPLAY_GT = ">"


class RuleExtractor:
    """Extract human-readable FAIL rules from a shallow balanced tree."""

    def __init__(self, settings: RuleExtractorSettings, seed: int) -> None:
        """Bind tree settings and RNG seed."""
        self._settings = settings
        self._seed = seed

    def extract(  # noqa: PLR0913, PLR0917
        self,
        x: npt.NDArray[np.floating],
        y_fail: npt.NDArray[np.bool_],
        names: list[str],
        space: ScenarioSpace,
        modes: Sequence[FailureModeSummary] = (),
        run_ids: Sequence[UUID] = (),
    ) -> list[Rule]:
        """Walk FAIL leaves with precision ≥ ``min_precision``.

        Implements: FR-ANA-004
        """
        matrix = np.asarray(x, dtype=np.float64)
        y = np.asarray(y_fail, dtype=np.int32)
        n = matrix.shape[0]
        if n == 0 or matrix.ndim != MATRIX_NDIM or len(np.unique(y)) < N_CLASSES_BINARY:
            return []
        min_leaf = max(
            self._settings.min_leaf_size_floor,
            math.ceil(self._settings.min_leaf_fraction * n),
        )
        tree = DecisionTreeClassifier(
            max_depth=self._settings.max_depth,
            min_samples_leaf=min_leaf,
            class_weight="balanced",
            random_state=self._seed,
        )
        tree.fit(matrix, y)
        rules: list[Rule] = []
        for path in _fail_paths(tree):
            precision = path[1] / path[2] if path[2] else 0.0
            if precision < self._settings.min_precision:
                continue
            merged = _merge_conditions(path[0])
            kept = merged[: self._settings.max_conditions]
            conditions = tuple(
                _to_condition(feat, op, thr, names, space)
                for feat, op, thr in kept
                if feat < len(names)
            )
            if not conditions:
                continue
            covered = _cover_mask(matrix, kept)
            fail_ids = (
                [run_ids[i] for i, flag in enumerate(covered) if flag and y[i] == _FAIL]
                if run_ids
                else []
            )
            mode_code = _best_mode(fail_ids, modes)
            primary = _majority_class(fail_ids, modes)
            text = render_rule(conditions, precision, int(path[1]), primary)
            rules.append(
                Rule(
                    conditions=conditions,
                    precision=float(precision),
                    support=int(path[1]),
                    primary_class=primary,
                    mode_code=mode_code,
                    text=text,
                )
            )
        rules.sort(key=lambda r: (r.precision * r.support, r.precision, r.support), reverse=True)
        return rules


def render_rule(
    conditions: Sequence[Condition],
    precision: float,
    support: int,
    primary: FailureClass | None,
    lexicon: LabelLexicon | None = None,
) -> str:
    """``IF a > x u AND b < y v THEN FAIL (precision …)``."""
    words = lexicon or LabelLexicon()
    parts: list[str] = []
    for cond in conditions:
        op = _DISPLAY_GT if cond.op == _RIGHT else cond.op
        phys = _format_physical(cond.threshold_physical, words.display_sigfigs)
        unit = "" if cond.unit in {"", "-"} else f" {cond.unit}"
        parts.append(f"{cond.param} {op} {phys}{unit}")
    body = " AND ".join(parts)
    cls = f", class {primary.value}" if primary is not None else ""
    return f"IF {body} THEN FAIL (precision {precision:.2f}, support {support} runs{cls})"


def _fail_paths(
    tree: DecisionTreeClassifier,
) -> list[tuple[list[tuple[int, Literal["<", "≥"], float]], int, int, list[float]]]:
    t = tree.tree_
    out: list[tuple[list[tuple[int, Literal["<", "≥"], float]], int, int, list[float]]] = []

    def walk(
        node: int,
        conds: list[tuple[int, Literal["<", "≥"], float]],
        gains: list[float],
    ) -> None:
        left, right = int(t.children_left[node]), int(t.children_right[node])
        if left == right:
            values = t.value[node][0]
            classes = [int(c) for c in tree.classes_]
            fail_i = classes.index(_FAIL) if _FAIL in classes else None
            n_fail = int(values[fail_i]) if fail_i is not None else 0
            n_total = int(values.sum())
            out.append((list(conds), n_fail, n_total, list(gains)))
            return
        feat = int(t.feature[node])
        thr = float(t.threshold[node])
        gain = float(t.impurity[node] - t.impurity[left] - t.impurity[right])
        walk(left, [*conds, (feat, _LEFT, thr)], [*gains, gain])
        walk(right, [*conds, (feat, _RIGHT, thr)], [*gains, gain])

    walk(0, [], [])
    return out


def _merge_conditions(
    conds: Sequence[tuple[int, Literal["<", "≥"], float]],
) -> list[tuple[int, Literal["<", "≥"], float]]:
    """Keep the tightest bound per (feature, op)."""
    lo: dict[int, float] = {}
    hi: dict[int, float] = {}
    order: list[tuple[int, Literal["<", "≥"]]] = []
    for feat, op, thr in conds:
        key = (feat, op)
        if op == _LEFT:
            if feat not in hi:
                order.append(key)
            hi[feat] = thr if feat not in hi else min(hi[feat], thr)
        else:
            if feat not in lo:
                order.append(key)
            lo[feat] = thr if feat not in lo else max(lo[feat], thr)
    merged: list[tuple[int, Literal["<", "≥"], float]] = []
    seen: set[tuple[int, Literal["<", "≥"]]] = set()
    for feat, op in order:
        if (feat, op) in seen:
            continue
        seen.add((feat, op))
        merged.append((feat, op, hi[feat] if op == _LEFT else lo[feat]))
    return merged


def _to_condition(
    feat: int,
    op: Literal["<", "≥"],
    thr: float,
    names: list[str],
    space: ScenarioSpace,
) -> Condition:
    pid = names[feat]
    spec = space.param(pid)
    physical = float(denormalize_param(spec, float(np.clip(thr, 0.0, 1.0))))
    return Condition(
        param=pid,
        op=op,
        threshold_unit=thr,
        threshold_physical=physical,
        unit=spec.unit,
    )


def _cover_mask(
    x: npt.NDArray[np.float64], conds: Sequence[tuple[int, Literal["<", "≥"], float]]
) -> npt.NDArray[np.bool_]:
    mask = np.ones(x.shape[0], dtype=np.bool_)
    for feat, op, thr in conds:
        mask &= x[:, feat] < thr if op == _LEFT else x[:, feat] >= thr
    return mask


def _best_mode(fail_ids: Sequence[UUID], modes: Sequence[FailureModeSummary]) -> str | None:
    if not fail_ids or not modes:
        return None
    s = set(fail_ids)
    best_code: str | None = None
    best = -1.0
    for mode in modes:
        members = set(mode.member_run_ids)
        union = len(s | members)
        j = (len(s & members) / union) if union else 0.0
        if j > best:
            best, best_code = j, mode.code or None
    return best_code


def _majority_class(
    fail_ids: Sequence[UUID], modes: Sequence[FailureModeSummary]
) -> FailureClass | None:
    if not fail_ids:
        return None
    counts: dict[FailureClass, int] = {}
    index = {rid: mode.primary_class for mode in modes for rid in mode.member_run_ids}
    for rid in fail_ids:
        cls = index.get(rid)
        if cls is not None:
            counts[cls] = counts.get(cls, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda k: (counts[k], k.value))


def _format_physical(value: float, sigfigs: int) -> str:
    return f"{value:.{sigfigs}g}"
