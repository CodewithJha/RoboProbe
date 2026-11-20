"""Mode summaries: ranges, medoid, minimal scenario, auto-label (docs/09 §3.3).

Implements: FR-ANA-002
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from uuid import UUID

import numpy as np
import numpy.typing as npt
from scipy.spatial.distance import cdist

from roboprobe.analysis.settings import LabelLexicon
from roboprobe.analysis.types import (
    AnalysisRun,
    ClusteringResult,
    FailureModeSummary,
    ParamRange,
)
from roboprobe.core.types import FailureClass, ParamValue
from roboprobe.scenario.normalize import from_unit, to_unit
from roboprobe.scenario.space import ParameterSpec, ScenarioSpace

__all__ = ["ModeSummarizer", "build_label"]

_NOISE = -1
_UNIT_SPAN = 1.0


class ModeSummarizer:
    """Turn cluster labels into :class:`FailureModeSummary` rows."""

    def __init__(
        self,
        *,
        characteristic_coverage: float,
        lexicon: LabelLexicon | None = None,
        seed: int = 0,
    ) -> None:
        """Bind coverage cut, label lexicon and sampling seed."""
        self._coverage = characteristic_coverage
        self._lexicon = lexicon or LabelLexicon()
        self._seed = seed

    def summarize(
        self,
        result: ClusteringResult,
        runs: Sequence[AnalysisRun],
        space: ScenarioSpace,
    ) -> list[FailureModeSummary]:
        """Summarise each non-noise cluster. Noise is never returned.

        Implements: FR-ANA-002
        """
        by_id = {run.id: run for run in runs}
        summaries: list[FailureModeSummary] = []
        for label in _positive_labels(result.labels):
            mask = result.labels == label
            member_ids = tuple(rid for rid, keep in zip(result.run_ids, mask, strict=True) if keep)
            members = [by_id[rid] for rid in member_ids]
            x = result.X[mask]
            medoid_i = _medoid_index(x, self._seed, self._lexicon.medoid_sample_cap)
            ranges, characteristic = _ranges(
                members, space, self._coverage, self._lexicon.quantile_lo, self._lexicon.quantile_hi
            )
            mix = _class_mix(members)
            primary = max(mix, key=lambda k: (mix[k], k.value))
            minimal = _minimal_run(members, space, characteristic)
            min_run = next(run for run in members if run.id == minimal)
            summary = FailureModeSummary(
                code="",
                size=len(member_ids),
                primary_class=primary,
                class_mix=mix,
                ranges=ranges,
                characteristic=characteristic,
                medoid_run_id=member_ids[medoid_i],
                minimal_run_id=minimal,
                minimal_values=dict(min_run.values),
                member_run_ids=member_ids,
                label="",
                provisional=result.provisional,
            )
            summaries.append(
                summary.model_copy(update={"label": build_label(summary, space, self._lexicon)})
            )
        return summaries


def build_label(
    summary: FailureModeSummary,
    space: ScenarioSpace,
    lexicon: LabelLexicon | None = None,
) -> str:
    """``"<CLASS> | p1 high · p2 low"`` from characteristic coverage rank."""
    words = lexicon or LabelLexicon()
    ranked = sorted(
        summary.characteristic,
        key=lambda pid: (summary.ranges[pid].space_coverage, pid),
    )[: words.top_n]
    if not ranked:
        return summary.primary_class.value
    nominal_u = space.to_unit(space.nominal_values())
    index = {spec.id: i for i, spec in enumerate(space.params)}
    parts: list[str] = []
    for pid in ranked:
        spec = space.param(pid)
        lo_u, hi_u = _unit_quantiles(summary.ranges[pid], spec)
        mid = 0.5 * (lo_u + hi_u)
        direction = words.high if mid > float(nominal_u[index[pid]]) else words.low
        parts.append(f"{_short_name(pid, words)} {direction}")
    return f"{summary.primary_class.value} | {words.joiner.join(parts)}"


def _positive_labels(labels: npt.NDArray[np.intp]) -> list[int]:
    return sorted({int(v) for v in labels.tolist() if int(v) != _NOISE})


def _class_mix(members: Sequence[AnalysisRun]) -> dict[FailureClass, float]:
    counts: Counter[FailureClass] = Counter()
    for run in members:
        if run.primary_failure is not None:
            counts[run.primary_failure] += 1
    total = sum(counts.values()) or 1
    if not counts:
        return {FailureClass.INFRA: 1.0}
    return {cls: n / total for cls, n in counts.items()}


def _ranges(
    members: Sequence[AnalysisRun],
    space: ScenarioSpace,
    coverage_cut: float,
    q_lo: float,
    q_hi: float,
) -> tuple[dict[str, ParamRange], frozenset[str]]:
    if not space.params:
        return {}, frozenset()
    u = np.vstack([space.to_unit(run.values) for run in members])
    ranges: dict[str, ParamRange] = {}
    characteristic: list[str] = []
    for col, spec in enumerate(space.params):
        lo = float(np.quantile(u[:, col], q_lo))
        hi = float(np.quantile(u[:, col], q_hi))
        span = (hi - lo) / _UNIT_SPAN
        p_lo = float(from_unit([spec], np.array([lo], dtype=np.float64))[spec.id])
        p_hi = float(from_unit([spec], np.array([hi], dtype=np.float64))[spec.id])
        ranges[spec.id] = ParamRange(unit=spec.unit, q05=p_lo, q95=p_hi, space_coverage=span)
        if span < coverage_cut:
            characteristic.append(spec.id)
    return ranges, frozenset(characteristic)


def _unit_quantiles(prange: ParamRange, spec: ParameterSpec) -> tuple[float, float]:
    lo = to_unit([spec], {spec.id: prange.q05})[0]
    hi = to_unit([spec], {spec.id: prange.q95})[0]
    return float(lo), float(hi)


def _minimal_run(
    members: Sequence[AnalysisRun],
    space: ScenarioSpace,
    characteristic: frozenset[str],
) -> UUID:
    nominal = space.to_unit(space.nominal_values())
    ids = [spec.id for spec in space.params]
    cols = [i for i, pid in enumerate(ids) if pid in characteristic] or list(range(len(ids)))
    best_id = members[0].id
    best = float("inf")
    for run in members:
        u = space.to_unit(run.values)
        dist = float(np.linalg.norm(u[cols] - nominal[cols]))
        if dist < best:
            best, best_id = dist, run.id
    return best_id


def _medoid_index(x: npt.NDArray[np.float64], seed: int, cap: int) -> int:
    n = x.shape[0]
    if n <= 1:
        return 0
    if n <= cap:
        d = cdist(x, x, metric="euclidean")
        return int(np.argmin(d.sum(axis=1)))
    rng = np.random.Generator(np.random.PCG64(seed))
    sample = rng.choice(n, size=cap, replace=False)
    d = cdist(x[sample], x[sample], metric="euclidean")
    return int(sample[int(np.argmin(d.sum(axis=1)))])


def _short_name(param_id: str, lexicon: LabelLexicon) -> str:
    tail = param_id.rsplit(".", 1)[-1]
    return lexicon.aliases.get(tail, tail)


def denormalize_param(spec: ParameterSpec, unit: float) -> ParamValue:
    """Map a unit-interval threshold to physical units (log-aware)."""
    return from_unit([spec], np.array([unit], dtype=np.float64))[spec.id]
