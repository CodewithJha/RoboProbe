"""Tests for :mod:`roboprobe.analysis.importance` (T-072, docs/09 §4)."""

from __future__ import annotations

import numpy as np
import pytest
from tests.unit.analysis.synthetic import planted_xor

from roboprobe.analysis.importance import ImportanceExplainer
from roboprobe.analysis.settings import ImportanceSettings

pytestmark = pytest.mark.unit


def test_planted_params_rank_top_and_interaction() -> None:
    settings = ImportanceSettings(max_iter=80, cv_folds=3, min_failures_confident=10)
    explainer = ImportanceExplainer(settings, seed=0)
    x, y, names = planted_xor(400, 6, seed=1, threshold=0.55)
    report = explainer.explain(x, y, names)
    ranking = np.argsort(-np.array(report.mean_abs_shap))
    assert set(ranking[:2].tolist()) == {0, 1}
    inter = np.array(report.interactions)
    off = inter.copy()
    np.fill_diagonal(off, -1.0)
    i, j = np.unravel_index(int(np.argmax(off)), off.shape)
    assert {int(i), int(j)} == {0, 1}
    assert report.low_confidence is False


def test_low_confidence_n_fail() -> None:
    x = np.array([[0.1, 0.2], [0.9, 0.8], [0.2, 0.1], [0.8, 0.9]])
    y = np.array([False, True, False, True])
    report = ImportanceExplainer(ImportanceSettings(min_failures_confident=10), seed=0).explain(
        x, y, ["a", "b"]
    )
    assert report.low_confidence is True


def test_low_confidence_auc_floor() -> None:
    rng = np.random.Generator(np.random.PCG64(3))
    x = rng.random((80, 3))
    y = rng.random(80) > 0.5
    settings = ImportanceSettings(min_failures_confident=1, min_cv_auc=0.99, cv_folds=3, max_iter=5)
    report = ImportanceExplainer(settings, seed=0).explain(x, y, ["a", "b", "c"])
    assert report.low_confidence is True


def test_deterministic_json() -> None:
    x, y, names = planted_xor(120, 4, seed=4)
    settings = ImportanceSettings(max_iter=40, cv_folds=2, shap_max_samples=80)
    a = ImportanceExplainer(settings, seed=9).explain(x, y, names)
    b = ImportanceExplainer(settings, seed=9).explain(x, y, names)
    assert a.model_dump() == b.model_dump()


def test_lengthscale_disagreement() -> None:
    x, y, names = planted_xor(200, 4, seed=5)
    lengthscales = {"p0": 10.0, "p1": 10.0, "p2": 0.1, "p3": 0.1}
    report = ImportanceExplainer(ImportanceSettings(max_iter=40, cv_folds=2), seed=0).explain(
        x, y, names, lengthscales=lengthscales
    )
    assert report.gp_normalized is not None
    assert report.disagreement


def test_empty_and_single_class() -> None:
    explainer = ImportanceExplainer(ImportanceSettings(), seed=0)
    empty = explainer.explain(np.zeros((0, 2)), np.zeros(0, dtype=np.bool_), ["a", "b"])
    assert empty.low_confidence is True
    one = explainer.explain(np.ones((3, 2)), np.ones(3, dtype=np.bool_), ["a", "b"])
    assert one.low_confidence is True


@pytest.mark.benchmark
def test_importance_2000x8_under_30s(benchmark: object) -> None:
    rng = np.random.Generator(np.random.PCG64(0))
    x = rng.random((400, 8))
    y = (x[:, 0] > 0.6) & (x[:, 1] > 0.6)
    explainer = ImportanceExplainer(
        ImportanceSettings(max_iter=30, cv_folds=2, shap_max_samples=50), seed=0
    )
    benchmark(explainer.explain, x, y, [f"p{i}" for i in range(8)])
