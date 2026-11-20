"""HistGB + SHAP importance with optional ARD lengthscale cross-check (docs/09 §4).

Implements: FR-ANA-003
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

import numpy as np
import numpy.typing as npt
import shap  # type: ignore[import-untyped]
from sklearn.ensemble import (  # type: ignore[import-untyped]
    GradientBoostingClassifier,
    HistGradientBoostingClassifier,
)
from sklearn.metrics import balanced_accuracy_score, roc_auc_score  # type: ignore[import-untyped]
from sklearn.model_selection import StratifiedKFold  # type: ignore[import-untyped]

from roboprobe.analysis._const import (
    DECISION_THRESHOLD,
    MATRIX_NDIM,
    N_CLASSES_BINARY,
    SHAP_INTERACTION_NDIM,
    SHAP_VALUES_NDIM,
)
from roboprobe.analysis.settings import ImportanceSettings
from roboprobe.analysis.types import FailureModeSummary, ImportanceReport

__all__ = ["ImportanceExplainer"]

_HIST = "hist_gradient_boosting"
_GBM = "gradient_boosting"


class ImportanceExplainer:
    """Fail-vs-pass explainer. Lengthscales are an optional mapping, not a GP object."""

    def __init__(self, settings: ImportanceSettings, seed: int) -> None:
        """Bind explainer settings and RNG seed."""
        self._settings = settings
        self._seed = seed

    def explain(  # noqa: PLR0913
        self,
        x: npt.NDArray[np.floating],
        y_fail: npt.NDArray[np.bool_],
        names: list[str],
        *,
        lengthscales: Mapping[str, float] | None = None,
        modes: Sequence[FailureModeSummary] = (),
        run_ids: Sequence[UUID] = (),
    ) -> ImportanceReport:
        """Fit a balanced tree ensemble and return mean |SHAP| plus interactions.

        Implements: FR-ANA-003
        """
        matrix = np.asarray(x, dtype=np.float64)
        y = np.asarray(y_fail, dtype=np.bool_)
        n_fail = int(y.sum())
        n_feat = matrix.shape[1] if matrix.ndim == MATRIX_NDIM else 0
        empty = _blank(names, n_feat)
        if matrix.size == 0 or n_feat == 0 or len(np.unique(y)) < N_CLASSES_BINARY:
            return empty
        model, kind = _fit_model(matrix, y, self._settings, self._seed)
        auc_mean, auc_std, bal_mean, bal_std = _cv_scores(matrix, y, self._settings, self._seed)
        auc_floor = auc_mean if auc_mean is not None else 0.0
        low = (
            n_fail < self._settings.min_failures_confident
            or auc_mean is None
            or auc_floor < self._settings.min_cv_auc
        )
        mean_abs, interactions = _shap_blocks(model, matrix, self._settings.shap_max_samples)
        gp_norm, disagree = _lengthscale_check(
            names, mean_abs, lengthscales, self._settings.rank_disagreement
        )
        per_mode = _per_mode(matrix, modes, run_ids, self._settings, self._seed)
        return ImportanceReport(
            names=tuple(names),
            mean_abs_shap=tuple(float(v) for v in mean_abs),
            interactions=tuple(tuple(float(v) for v in row) for row in interactions),
            auc_mean=auc_mean,
            auc_std=auc_std,
            balanced_acc_mean=bal_mean,
            balanced_acc_std=bal_std,
            low_confidence=low,
            model_kind=kind,
            gp_normalized=gp_norm,
            disagreement=disagree,
            per_mode=per_mode,
        )


def _blank(names: list[str], n_feat: int) -> ImportanceReport:
    dim = n_feat or len(names)
    zeros = tuple(0.0 for _ in range(dim))
    inter = tuple(zeros for _ in range(dim))
    return ImportanceReport(
        names=tuple(names) if names else tuple(f"p{i}" for i in range(dim)),
        mean_abs_shap=zeros,
        interactions=inter,
        auc_mean=None,
        auc_std=None,
        balanced_acc_mean=None,
        balanced_acc_std=None,
        low_confidence=True,
        model_kind=_HIST,
        gp_normalized=None,
        disagreement=(),
        per_mode={},
    )


def _fit_model(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.bool_],
    settings: ImportanceSettings,
    seed: int,
) -> tuple[object, str]:
    y_int = y.astype(np.int32)
    hist = HistGradientBoostingClassifier(
        max_depth=settings.max_depth,
        learning_rate=settings.learning_rate,
        max_iter=settings.max_iter,
        class_weight="balanced",
        random_state=seed,
    )
    try:
        hist.fit(x, y_int)
    except (ValueError, TypeError):
        gbm = GradientBoostingClassifier(
            max_depth=settings.max_depth,
            learning_rate=settings.learning_rate,
            n_estimators=settings.max_iter,
            random_state=seed,
        )
        gbm.fit(x, y_int)
        return gbm, _GBM
    else:
        return hist, _HIST


def _cv_scores(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.bool_],
    settings: ImportanceSettings,
    seed: int,
) -> tuple[float | None, float | None, float | None, float | None]:
    counts = np.bincount(y.astype(np.int32), minlength=N_CLASSES_BINARY)
    folds = min(settings.cv_folds, int(counts.min()))
    if folds < N_CLASSES_BINARY:
        return None, None, None, None
    splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    aucs: list[float] = []
    bals: list[float] = []
    y_int = y.astype(np.int32)
    for train, test in splitter.split(x, y_int):
        model, _ = _fit_model(x[train], y[train], settings, seed)
        proba = _predict_fail_proba(model, x[test])
        pred = proba >= DECISION_THRESHOLD
        if len(np.unique(y_int[test])) > 1:
            aucs.append(float(roc_auc_score(y_int[test], proba)))
        bals.append(float(balanced_accuracy_score(y_int[test], pred)))
    if not aucs:
        return None, None, float(np.mean(bals)), float(np.std(bals))
    return float(np.mean(aucs)), float(np.std(aucs)), float(np.mean(bals)), float(np.std(bals))


def _predict_fail_proba(model: object, x: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    proba = np.asarray(model.predict_proba(x), dtype=np.float64)  # type: ignore[attr-defined]
    classes = list(model.classes_)  # type: ignore[attr-defined]
    if 1 in classes:
        return proba[:, classes.index(1)]
    return np.zeros(x.shape[0], dtype=np.float64)


def _shap_blocks(
    model: object, x: npt.NDArray[np.float64], max_samples: int
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    d = x.shape[1]
    sample = x if x.shape[0] <= max_samples else x[:max_samples]
    try:
        explainer = shap.TreeExplainer(model)
        values = np.asarray(explainer.shap_values(sample), dtype=np.float64)
        if values.ndim == SHAP_VALUES_NDIM:
            values = values[:, :, -1]
        mean_abs = np.mean(np.abs(values), axis=0)
        interactions = np.zeros((d, d), dtype=np.float64)
        try:
            inter = np.asarray(explainer.shap_interaction_values(sample), dtype=np.float64)
            if inter.ndim == SHAP_INTERACTION_NDIM:
                inter = inter[:, :, :, -1]
            for i in range(d):
                for j in range(d):
                    if i == j:
                        continue
                    interactions[i, j] = float(np.mean(np.abs(inter[:, i, j])))
        except (ValueError, TypeError, AttributeError):
            pass
        return np.asarray(mean_abs, dtype=np.float64), interactions
    except (ImportError, ValueError, TypeError, AttributeError):
        return np.zeros(d, dtype=np.float64), np.zeros((d, d), dtype=np.float64)


def _lengthscale_check(
    names: list[str],
    shap_mean: npt.NDArray[np.float64],
    lengthscales: Mapping[str, float] | None,
    gap: int,
) -> tuple[tuple[float, ...] | None, tuple[str, ...]]:
    if not lengthscales:
        return None, ()
    tiny = np.finfo(float).tiny
    inv = np.array(
        [1.0 / max(float(lengthscales.get(n, np.inf)), tiny) for n in names],
        dtype=np.float64,
    )
    total = float(inv.sum())
    norm = inv / total if total else inv
    shap_rank = np.argsort(-shap_mean)
    gp_rank = np.argsort(-norm)
    shap_pos = {int(idx): pos for pos, idx in enumerate(shap_rank)}
    gp_pos = {int(idx): pos for pos, idx in enumerate(gp_rank)}
    disagree = tuple(names[i] for i in range(len(names)) if abs(shap_pos[i] - gp_pos[i]) >= gap)
    return tuple(float(v) for v in norm), disagree


def _per_mode(
    x: npt.NDArray[np.float64],
    modes: Sequence[FailureModeSummary],
    run_ids: Sequence[UUID],
    settings: ImportanceSettings,
    seed: int,
) -> dict[str, tuple[float, ...]]:
    if not modes or not run_ids or len(run_ids) != x.shape[0]:
        return {}
    index = {rid: i for i, rid in enumerate(run_ids)}
    out: dict[str, tuple[float, ...]] = {}
    for mode in modes:
        if mode.size < settings.min_failures_confident:
            continue
        mask = np.zeros(x.shape[0], dtype=np.bool_)
        for rid in mode.member_run_ids:
            if rid in index:
                mask[index[rid]] = True
        if int(mask.sum()) < settings.min_failures_confident:
            continue
        y_mode = mask
        if len(np.unique(y_mode)) < N_CLASSES_BINARY:
            continue
        model, _ = _fit_model(x, y_mode, settings, seed)
        mean_abs, _ = _shap_blocks(model, x, settings.shap_max_samples)
        out[mode.code or str(mode.medoid_run_id)] = tuple(float(v) for v in mean_abs)
    return out
