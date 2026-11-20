"""HDBSCAN clustering of failing runs with a small-n class fallback (docs/09 §3.2).

Implements: FR-ANA-001
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt
from sklearn.cluster import HDBSCAN  # type: ignore[import-untyped]

from roboprobe.analysis._const import HDBSCAN_MIN_SIZE_ABS
from roboprobe.analysis.settings import ClustererSettings
from roboprobe.analysis.types import ClusteringResult, FeatureMatrix
from roboprobe.core.types import FailureClass

__all__ = ["FailureClusterer"]

_NOISE = -1
_UNIT_PROB = 1.0


class FailureClusterer:
    """Cluster a :class:`FeatureMatrix` (docs/05 §7)."""

    def __init__(self, settings: ClustererSettings) -> None:
        """Bind clustering settings."""
        self._settings = settings

    def fit(self, features: FeatureMatrix) -> ClusteringResult:
        """Fit HDBSCAN, or group by failure class when ``n_fail`` is below the floor.

        Implements: FR-ANA-001

        Rows are sorted by ``run_id`` before fitting so labels are permutation-invariant.
        """
        n_fail = features.X.shape[0]
        order = np.argsort([rid.bytes for rid in features.run_ids])
        x = np.asarray(features.X[order], dtype=np.float64)
        run_ids = tuple(features.run_ids[i] for i in order)
        classes = tuple(features.classes[i] for i in order)
        min_size = max(
            self._settings.min_cluster_size_floor,
            math.ceil(self._settings.min_cluster_fraction * n_fail),
        )
        if n_fail == 0:
            return _empty(min_size)
        if n_fail < self._settings.min_failures_for_clustering:
            labels, probabilities = _by_class(classes, n_fail)
            return ClusteringResult(
                labels=labels,
                probabilities=probabilities,
                outlier_scores=1.0 - probabilities,
                method="class_fallback",
                min_cluster_size=min_size,
                provisional=True,
                run_ids=run_ids,
                X=x,
            )
        min_samples = self._settings.min_samples if self._settings.min_samples else min_size
        model = HDBSCAN(
            min_cluster_size=max(min_size, HDBSCAN_MIN_SIZE_ABS),
            min_samples=min_samples,
            metric="euclidean",
            cluster_selection_method="eom",
            store_centers=None,
            copy=True,
        )
        raw = np.asarray(model.fit_predict(x), dtype=np.intp)
        probabilities = np.asarray(model.probabilities_, dtype=np.float64)
        outlier = getattr(model, "outlier_scores_", None)
        scores = (
            np.asarray(outlier, dtype=np.float64) if outlier is not None else (1.0 - probabilities)
        )
        return ClusteringResult(
            labels=raw,
            probabilities=probabilities,
            outlier_scores=scores,
            method="hdbscan",
            min_cluster_size=min_size,
            provisional=False,
            run_ids=run_ids,
            X=x,
        )


def _empty(min_size: int) -> ClusteringResult:
    z = np.zeros((0, 0), dtype=np.float64)
    return ClusteringResult(
        labels=np.zeros(0, dtype=np.intp),
        probabilities=np.zeros(0, dtype=np.float64),
        outlier_scores=np.zeros(0, dtype=np.float64),
        method="hdbscan",
        min_cluster_size=min_size,
        provisional=False,
        run_ids=(),
        X=z,
    )


def _by_class(
    classes: tuple[FailureClass | None, ...], n_fail: int
) -> tuple[npt.NDArray[np.intp], npt.NDArray[np.float64]]:
    labels = np.full(n_fail, _NOISE, dtype=np.intp)
    known = sorted({c for c in classes if c is not None}, key=lambda c: c.value)
    index = {cls: i for i, cls in enumerate(known)}
    for i, cls in enumerate(classes):
        if cls is not None:
            labels[i] = index[cls]
    return labels, np.full(n_fail, _UNIT_PROB, dtype=np.float64)
