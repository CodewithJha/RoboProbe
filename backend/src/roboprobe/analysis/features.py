"""Per-failing-run feature matrix (docs/09 §3.1).

Implements: FR-ANA-001
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final
from uuid import UUID

import numpy as np
import numpy.typing as npt

from roboprobe.analysis.types import AnalysisRun, FeatureDiagnostics, FeatureMatrix
from roboprobe.core.settings.analysis import FeatureWeights
from roboprobe.core.settings.oracles import OracleThresholds
from roboprobe.core.types import FailureClass, Phase, Verdict
from roboprobe.scenario.space import ScenarioSpace

__all__ = [
    "TRAJ_COLUMNS",
    "FailureFeatureBuilder",
]

TRAJ_COLUMNS: Final[tuple[str, str, str, str]] = (
    "s_fail_over_L",
    "t_fail_over_T_max",
    "min_clearance_over_d_norm",
    "max_loc_error_over_e_max",
)
_METRIC_S: Final = "s_fail"
_METRIC_L: Final = "L_nominal"
_METRIC_T: Final = "t_fail"
_METRIC_TMAX: Final = "T_max"
_METRIC_CLEAR: Final = "min_clearance"
_METRIC_LOC: Final = "max_loc_error"
_SKIP_PHASES: Final[frozenset[Phase]] = frozenset({"confirm"})
_UNIT_HI: Final = 1.0
_UNIT_LO: Final = 0.0


def _space_version_int(version: str) -> int:
    try:
        return int(version, 16)
    except ValueError:
        return 0


class FailureFeatureBuilder:
    """Build the weighted clustering features of failing runs.

    Args:
        weights: Block weights from ``analysis.feature_weights``.
    """

    def __init__(self, weights: FeatureWeights) -> None:
        """Bind feature-block weights."""
        self._weights = weights

    def build(self, runs: Sequence[AnalysisRun], space: ScenarioSpace) -> FeatureMatrix:
        """Return rows for ``verdict == FAIL`` runs outside the confirm phase.

        Implements: FR-ANA-001

        Invalid runs are counted, never encoded. Missing trajectory metrics become 0.
        """
        n_invalid = sum(1 for run in runs if run.verdict is Verdict.INVALID)
        fails = [
            run for run in runs if run.verdict is Verdict.FAIL and run.phase not in _SKIP_PHASES
        ]
        classes = tuple(FailureClass)
        param_ids = tuple(spec.id for spec in space.params)
        columns = param_ids + tuple(cls.value for cls in classes) + TRAJ_COLUMNS
        n_fail = len(fails)
        dim = len(columns)
        x = np.zeros((n_fail, dim), dtype=np.float64)
        missing_traj = False
        w_param, w_class, w_traj = (
            self._weights.param,
            self._weights.class_,
            self._weights.traj,
        )
        n_param = len(param_ids)
        n_cls = len(classes)
        class_index = {cls: i for i, cls in enumerate(classes)}
        run_ids: list[UUID] = []
        row_classes: list[FailureClass | None] = []
        for i, run in enumerate(fails):
            run_ids.append(run.id)
            row_classes.append(run.primary_failure)
            if n_param:
                x[i, :n_param] = space.to_unit(run.values) * w_param
            if run.primary_failure is not None:
                x[i, n_param + class_index[run.primary_failure]] = w_class
            traj, gap = _traj_block(run, run.oracle_thresholds)
            missing_traj = missing_traj or gap
            x[i, n_param + n_cls :] = traj * w_traj
        diagnostics = FeatureDiagnostics(
            n_input=len(runs),
            n_fail=n_fail,
            n_excluded_invalid=n_invalid,
            missing_traj=missing_traj,
        )
        return FeatureMatrix(
            X=x,
            run_ids=tuple(run_ids),
            columns=columns,
            space_version=_space_version_int(space.version),
            classes=tuple(row_classes),
            diagnostics=diagnostics,
        )


def _traj_block(
    run: AnalysisRun, thresholds: OracleThresholds
) -> tuple[npt.NDArray[np.float64], bool]:
    metrics = run.metrics
    needed = (_METRIC_S, _METRIC_L, _METRIC_T, _METRIC_TMAX, _METRIC_CLEAR, _METRIC_LOC)
    missing = any(key not in metrics for key in needed)
    length = metrics.get(_METRIC_L, 0.0)
    t_max = metrics.get(_METRIC_TMAX, 0.0)
    d_norm = thresholds.clear.d_norm
    e_max = thresholds.loc.e_max
    raw = np.array(
        [
            metrics.get(_METRIC_S, 0.0) / length if length else 0.0,
            metrics.get(_METRIC_T, 0.0) / t_max if t_max else 0.0,
            metrics.get(_METRIC_CLEAR, 0.0) / d_norm if d_norm else 0.0,
            metrics.get(_METRIC_LOC, 0.0) / e_max if e_max else 0.0,
        ],
        dtype=np.float64,
    )
    return np.clip(raw, _UNIT_LO, _UNIT_HI), missing
