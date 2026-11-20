"""Tests for :mod:`roboprobe.analysis.clustering` (T-070b, docs/09 §3.2)."""

from __future__ import annotations

from uuid import UUID

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from sklearn.metrics import adjusted_rand_score

from roboprobe.analysis.clustering import FailureClusterer
from roboprobe.analysis.settings import ClustererSettings
from roboprobe.analysis.types import FeatureDiagnostics, FeatureMatrix
from roboprobe.core.types import FailureClass

pytestmark = pytest.mark.unit

_NOISE = -1


def _matrix(
    x: np.ndarray,
    classes: tuple[FailureClass | None, ...] | None = None,
) -> FeatureMatrix:
    n = x.shape[0]
    ids = tuple(UUID(int=i + 1) for i in range(n))
    if classes is None:
        classes = tuple(FailureClass.COL for _ in range(n))
    return FeatureMatrix(
        X=x,
        run_ids=ids,
        columns=tuple(f"c{i}" for i in range(x.shape[1] or 1)),
        space_version=1,
        classes=classes,
        diagnostics=FeatureDiagnostics(
            n_input=n, n_fail=n, n_excluded_invalid=0, missing_traj=False
        ),
    )


def test_gaussian_blobs_ari() -> None:
    rng = np.random.Generator(np.random.PCG64(0))
    blobs = [
        rng.normal(loc=center, scale=0.05, size=(40, 4))
        for center in ([0.0, 0.0, 0.0, 0.0], [3.0, 0.0, 0.0, 0.0], [0.0, 3.0, 0.0, 0.0])
    ]
    x = np.vstack(blobs)
    truth = np.repeat([0, 1, 2], 40)
    result = FailureClusterer(
        ClustererSettings(min_cluster_size_floor=8, min_cluster_fraction=0.03)
    ).fit(_matrix(x))
    labeled = result.labels != _NOISE
    assert labeled.sum() >= 90
    ari = adjusted_rand_score(truth[labeled], result.labels[labeled])
    assert ari >= 0.9
    assert result.method == "hdbscan"
    assert result.provisional is False


def test_small_n_fallback_groups_by_class() -> None:
    x = np.eye(4)
    classes = (FailureClass.COL, FailureClass.COL, FailureClass.LOC, FailureClass.LOC)
    result = FailureClusterer(ClustererSettings()).fit(_matrix(x, classes))
    assert result.method == "class_fallback"
    assert result.provisional is True
    assert len(set(result.labels.tolist())) == 2


def test_n_fail_zero_empty() -> None:
    empty = np.zeros((0, 3))
    result = FailureClusterer(ClustererSettings()).fit(_matrix(empty, ()))
    assert result.labels.shape == (0,)
    assert result.run_ids == ()


def test_permutation_invariant_labels() -> None:
    rng = np.random.Generator(np.random.PCG64(1))
    x = np.vstack([rng.normal(0, 0.04, (30, 3)), rng.normal(4, 0.04, (30, 3))])
    base = _matrix(x)
    perm = rng.permutation(x.shape[0])
    shuffled = FeatureMatrix(
        X=x[perm],
        run_ids=tuple(base.run_ids[i] for i in perm),
        columns=base.columns,
        space_version=1,
        classes=tuple(base.classes[i] for i in perm),
        diagnostics=base.diagnostics,
    )
    settings = ClustererSettings(min_cluster_size_floor=8)
    a = FailureClusterer(settings).fit(base)
    b = FailureClusterer(settings).fit(shuffled)
    map_a = dict(zip(a.run_ids, a.labels.tolist(), strict=True))
    map_b = dict(zip(b.run_ids, b.labels.tolist(), strict=True))
    assert map_a == map_b


@given(st.integers(0, 12), st.integers(1, 6))
def test_labels_length_and_noise(n: int, d: int) -> None:
    x = np.random.default_rng(n + d).random((n, d))
    classes = tuple(FailureClass.COL for _ in range(n))
    result = FailureClusterer(ClustererSettings()).fit(_matrix(x, classes))
    assert result.labels.shape == (n,)
    assert set(result.labels.tolist()) <= set(range(max(n, 1))) | {_NOISE}


@pytest.mark.benchmark
def test_cluster_2000_rows_under_one_second(benchmark: object) -> None:
    rng = np.random.Generator(np.random.PCG64(2))
    x = rng.normal(size=(2000, 8))
    clusterer = FailureClusterer(ClustererSettings(min_cluster_size_floor=20))
    matrix = _matrix(x)
    benchmark(clusterer.fit, matrix)
