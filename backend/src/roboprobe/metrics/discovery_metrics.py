"""Reference-based discovery metrics MET-02, MET-04, MET-08, MET-09.

Implements: FR-EXP-001, FR-EXP-003, MET-02, MET-04, MET-08, MET-09
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import numpy as np
import numpy.typing as npt
from scipy.spatial import cKDTree

from roboprobe.core.settings.experiments import ExperimentSettings
from roboprobe.core.types import Verdict
from roboprobe.metrics.campaign_metrics import CampaignRun, comparison_runs

__all__ = [
    "NOVEL_LABEL",
    "bin_coverage_c2",
    "boundary_accuracy",
    "comparison_unit_points",
    "discovery_auc",
    "discovery_curve",
    "failing_unit_points",
    "failure_region_coverage",
    "label_failures",
    "pooled_cluster_hits",
    "unique_gt_modes",
]

type FloatArray = npt.NDArray[np.float64]
type IntArray = npt.NDArray[np.intp]
PAIRWISE_DIMS = 2
NOVEL_LABEL = "novel"
"""MET-02 label when no failing reference point lies within the match radius."""
P_FAIL_THRESHOLD = 0.5
"""Decision threshold for ``p_fail(x) > 0.5`` (docs/19 §3 MET-08, docs/09 §5.5)."""

_EXPERIMENT = ExperimentSettings()
_DEFAULT_RADIUS = _EXPERIMENT.mode_match_radius
_DEFAULT_BINS = _EXPERIMENT.coverage_bins
_NOISE_LABEL = -1


def _as_2d(points: npt.ArrayLike) -> FloatArray:
    """Shape ``(n, d)`` float64 points."""
    array = np.asarray(points, dtype=np.float64)
    if array.size == 0:
        return np.empty((0, 0), dtype=np.float64)
    if array.ndim == 1:
        return array.reshape(1, -1)
    return np.reshape(array, (array.shape[0], -1))


def _failing_points(runs: Sequence[CampaignRun]) -> FloatArray:
    cmp_runs = comparison_runs(runs)
    fails = [run.x_unit for run in cmp_runs if run.verdict is Verdict.FAIL]
    if not fails:
        d = len(cmp_runs[0].x_unit) if cmp_runs and cmp_runs[0].x_unit else 0
        return np.empty((0, d), dtype=np.float64)
    return np.asarray(fails, dtype=np.float64)


def label_failures(
    failures: npt.ArrayLike,
    ref_fail: npt.ArrayLike,
    ref_labels: Sequence[str],
    radius: float = _DEFAULT_RADIUS,
) -> list[str]:
    """GT mode of the nearest failing reference point within ``radius``, else novel.

    ``radius`` is ``experiments.mode_match_radius`` (unit L2, docs/19 §3 MET-02).
    """
    x = _as_2d(failures)
    ref = _as_2d(ref_fail)
    if x.shape[0] == 0:
        return []
    if ref.shape[0] == 0:
        return [NOVEL_LABEL] * x.shape[0]
    tree = cKDTree(ref)
    queried = tree.query(x, k=1)
    dist = np.asarray(queried[0], dtype=np.float64).reshape(-1)
    idx = np.asarray(queried[1], dtype=np.intp).reshape(-1)
    return [
        ref_labels[int(j)] if float(d) <= radius else NOVEL_LABEL
        for d, j in zip(dist, idx, strict=True)
    ]


def unique_gt_modes(
    failures: npt.ArrayLike,
    ref_fail: npt.ArrayLike,
    ref_labels: Sequence[str],
    radius: float = _DEFAULT_RADIUS,
) -> int:
    """MET-02 (k2d): number of GT modes hit by campaign failures.

    Novel matches are not counted. Pass unit-cube failure coordinates
    (extract with :func:`failing_unit_points`).

    Implements: MET-02.
    """
    labelled = label_failures(failures, ref_fail, ref_labels, radius)
    labels = {lab for lab in labelled if lab != NOVEL_LABEL}
    return len(labels)


def failing_unit_points(runs: Sequence[CampaignRun]) -> FloatArray:
    """Unit-cube coordinates of comparison-run failures."""
    return _failing_points(runs)


def comparison_unit_points(runs: Sequence[CampaignRun]) -> FloatArray:
    """Unit-cube coordinates of comparison runs that have ``x_unit`` set."""
    cmp_runs = comparison_runs(runs)
    xs = [run.x_unit for run in cmp_runs if run.x_unit]
    return np.asarray(xs, dtype=np.float64) if xs else np.empty((0, 0), dtype=np.float64)


def pooled_cluster_hits(
    failures_by_strategy: Mapping[str, npt.ArrayLike],
    radius: float = _DEFAULT_RADIUS,
    labels: npt.ArrayLike | None = None,
) -> dict[str, int]:
    """MET-02 (Gazebo): clusters hit per strategy after pooled clustering.

    Concatenates all strategies' failures (same seed index), clusters jointly
    with a unit-L2 radius graph (connected components) unless ``labels`` is
    supplied for the concatenated rows. Noise label ``-1`` is ignored.

    Implements: MET-02 pooled clustering (docs/19 §3).
    """
    names = list(failures_by_strategy)
    chunks = [_as_2d(failures_by_strategy[name]) for name in names]
    counts = [chunk.shape[0] for chunk in chunks]
    dim = next((chunk.shape[1] for chunk in chunks if chunk.shape[1]), 0)
    parts = [chunk if chunk.size else np.empty((0, dim), dtype=np.float64) for chunk in chunks]
    pooled = (
        np.vstack(parts)
        if any(count > 0 for count in counts)
        else np.empty((0, dim), dtype=np.float64)
    )
    if labels is None:
        assigned = _radius_clusters(pooled, radius)
    else:
        assigned = np.asarray(labels, dtype=np.intp).reshape(-1)
        if assigned.size != pooled.shape[0]:
            msg = "labels length must match the concatenated failure count"
            raise ValueError(msg)
    offset = 0
    hits: dict[str, int] = {}
    for name, count in zip(names, counts, strict=True):
        slice_labels = assigned[offset : offset + count]
        offset += count
        uniq = {int(lab) for lab in slice_labels if int(lab) != _NOISE_LABEL}
        hits[name] = len(uniq)
    return hits


def _radius_clusters(points: FloatArray, radius: float) -> IntArray:
    """Connected components of the undirected radius graph on ``points``."""
    n = points.shape[0]
    parent = np.arange(n, dtype=np.intp)
    if n == 0:
        return parent

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[int(parent[i])]
            i = int(parent[i])
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    if n == 1:
        return parent
    tree = cKDTree(points)
    for i, j in tree.query_pairs(radius, output_type="ndarray"):
        union(int(i), int(j))
    return np.asarray([find(i) for i in range(n)], dtype=np.intp)


def _bin_index(x: FloatArray, k: int) -> IntArray:
    """Bin each unit-interval coordinate into ``0 .. k-1``."""
    scaled = np.floor(x * k).astype(np.intp)
    return np.clip(scaled, 0, k - 1)


def bin_coverage_c2(
    points: npt.ArrayLike,
    k: int = _DEFAULT_BINS,
) -> float:
    """MET-04a: 2-way bin coverage ``C2``.

    ``C2 = (# of (i, j, b_i, b_j) cells hit) / (C(d, 2) * k^2)`` with ``k`` from
    ``experiments.coverage_bins`` (docs/19 §3). ``d < 2`` returns ``nan``.
    """
    packed = _as_2d(points)
    if packed.shape[0] == 0 or packed.shape[1] < PAIRWISE_DIMS:
        return float("nan")
    d = packed.shape[1]
    bins = _bin_index(packed, k)
    hit: set[tuple[int, int, int, int]] = set()
    for i in range(d):
        for j in range(i + 1, d):
            for row in bins:
                hit.add((i, j, int(row[i]), int(row[j])))
    n_pairs = d * (d - 1) // 2
    denom = n_pairs * k * k
    return float(len(hit) / denom)


def failure_region_coverage(
    failures: npt.ArrayLike,
    ref_fail: npt.ArrayLike,
    radius: float = _DEFAULT_RADIUS,
) -> float:
    """MET-04b: fraction of ``REF_fail`` within ``radius`` of a campaign failure.

    Implements: MET-04 CF (k2d only). Empty ``REF_fail`` returns ``nan``.
    """
    fail_pts = _as_2d(failures)
    ref = _as_2d(ref_fail)
    if ref.shape[0] == 0:
        return float("nan")
    if fail_pts.shape[0] == 0:
        return 0.0
    tree = cKDTree(fail_pts)
    queried = tree.query(ref, k=1)
    dist = np.asarray(queried[0], dtype=np.float64).reshape(-1)
    return float(np.mean(dist <= radius))


def boundary_accuracy(
    p_fail: npt.ArrayLike,
    ref_fail_mask: npt.ArrayLike,
    threshold: float = P_FAIL_THRESHOLD,
) -> tuple[float, float, float]:
    """MET-08: balanced accuracy, failure recall, and F1 of ``p_fail > threshold``.

    ``ref_fail_mask`` is true where the reference verdict is FAIL (docs/09 §5.5).

    Implements: MET-08.
    """
    p = np.asarray(p_fail, dtype=np.float64).reshape(-1)
    y = np.asarray(ref_fail_mask, dtype=np.bool_).reshape(-1)
    if p.size != y.size:
        msg = "p_fail and ref_fail_mask must have the same length"
        raise ValueError(msg)
    if p.size == 0:
        return float("nan"), float("nan"), float("nan")
    pred = p > threshold
    tp = int(np.sum(pred & y))
    tn = int(np.sum(~pred & ~y))
    fp = int(np.sum(pred & ~y))
    fn = int(np.sum(~pred & y))
    tpr = tp / (tp + fn) if (tp + fn) else float("nan")
    tnr = tn / (tn + fp) if (tn + fp) else float("nan")
    bal = float("nan") if math.isnan(tpr) or math.isnan(tnr) else 0.5 * (tpr + tnr)
    prec = tp / (tp + fp) if (tp + fp) else float("nan")
    if math.isnan(tpr) or math.isnan(prec) or (prec + tpr) == 0.0:
        f1 = float("nan")
    else:
        f1 = 2.0 * prec * tpr / (prec + tpr)
    return float(bal), float(tpr), float(f1)


def discovery_curve(
    run_mode_labels: Sequence[str | None],
    n_gt: int,
) -> FloatArray:
    """Cumulative unique GT modes after each proposal ``modes(n)``.

    ``run_mode_labels[i]`` is the GT id hit by run ``i`` (1-based n = i+1),
    ``None`` when the run is not a labelled GT hit (pass, invalid, novel).
    The series is monotone non-decreasing.
    """
    seen: set[str] = set()
    curve = np.empty(len(run_mode_labels), dtype=np.float64)
    for i, label in enumerate(run_mode_labels):
        if label is not None and label != NOVEL_LABEL:
            seen.add(label)
        curve[i] = float(len(seen))
    if n_gt < 0:
        msg = "n_gt must be non-negative"
        raise ValueError(msg)
    return curve


def discovery_auc(
    run_mode_labels: Sequence[str | None],
    n_gt: int,
    budget: int | None = None,
) -> float:
    """MET-09: ``AUC = (1/B) Σ_{n=1..B} modes(n)/|GT|``.

    If ``budget`` is longer than the label series, the curve is held at its last
    value (no further discoveries). Empty GT → ``nan``.

    Implements: MET-09.
    """
    if n_gt == 0:
        return float("nan")
    b = len(run_mode_labels) if budget is None else budget
    if b == 0:
        return float("nan")
    curve = discovery_curve(run_mode_labels, n_gt)
    if curve.size == 0:
        padded = np.zeros(b, dtype=np.float64)
    elif curve.size < b:
        padded = np.empty(b, dtype=np.float64)
        padded[: curve.size] = curve
        padded[curve.size :] = curve[-1]
    else:
        padded = curve[:b]
    return float(np.mean(padded / n_gt))
