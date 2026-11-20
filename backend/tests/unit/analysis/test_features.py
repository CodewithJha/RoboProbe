"""Tests for :mod:`roboprobe.analysis.features` (T-070a, docs/09 §3.1)."""

from __future__ import annotations

import hashlib

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tests.unit.analysis.conftest import make_run

from roboprobe.analysis.features import TRAJ_COLUMNS, FailureFeatureBuilder
from roboprobe.core.settings import load_settings
from roboprobe.core.settings.analysis import FeatureWeights
from roboprobe.core.types import FailureClass, Verdict

pytestmark = pytest.mark.unit


def test_hand_computed_rows(space: object) -> None:
    weights = FeatureWeights(param=1.0, class_=0.75, traj=0.5)
    builder = FailureFeatureBuilder(weights)
    runs = [
        make_run(),
        make_run(
            primary_failure=FailureClass.LOC,
            metrics={
                "s_fail": 5.0,
                "L_nominal": 10.0,
                "t_fail": 10.0,
                "T_max": 20.0,
                "min_clearance": 0.5,
                "max_loc_error": 0.5,
            },
        ),
        make_run(primary_failure=FailureClass.TIMEOUT),
    ]
    matrix = builder.build(runs, space)  # type: ignore[arg-type]
    assert matrix.X.shape[0] == 3
    assert matrix.diagnostics.n_fail == 3
    u0 = space.to_unit(runs[0].values)  # type: ignore[union-attr]
    np.testing.assert_allclose(matrix.X[0, : space.dim], u0 * weights.param)  # type: ignore[union-attr]
    class_start = space.dim  # type: ignore[union-attr]
    classes = list(FailureClass)
    assert matrix.X[0, class_start + classes.index(FailureClass.COL)] == pytest.approx(0.75)
    traj = matrix.X[1, class_start + len(classes) :]
    np.testing.assert_allclose(traj, np.array([0.5, 0.5, 1.0, 1.0]) * weights.traj)


def test_pinned_parameters_excluded(space: object) -> None:
    pinned = space.with_pins({"comms.cmd_delay_ms": 20.0})  # type: ignore[union-attr]
    matrix = FailureFeatureBuilder(FeatureWeights()).build([make_run()], pinned)
    assert "comms.cmd_delay_ms" not in matrix.columns
    assert matrix.X.shape[1] == pinned.dim + len(FailureClass) + len(TRAJ_COLUMNS)


def test_traj_weight_from_env(
    space: object, settings_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    del settings_env
    monkeypatch.setenv("ROBOPROBE_ANALYSIS__FEATURE_WEIGHTS__TRAJ", "0")
    weights = load_settings().analysis.feature_weights
    matrix = FailureFeatureBuilder(weights).build([make_run()], space)  # type: ignore[arg-type]
    n_cls = len(FailureClass)
    assert np.all(matrix.X[0, space.dim + n_cls :] == 0.0)  # type: ignore[union-attr]


def test_builder_is_pure(space: object) -> None:
    runs = [make_run(), make_run(primary_failure=FailureClass.NEAR)]
    builder = FailureFeatureBuilder(FeatureWeights())
    a = builder.build(runs, space)  # type: ignore[arg-type]
    b = builder.build(runs, space)  # type: ignore[arg-type]
    assert hashlib.sha256(a.X.tobytes()).digest() == hashlib.sha256(b.X.tobytes()).digest()


def test_invalid_and_confirm_excluded(space: object) -> None:
    runs = [
        make_run(),
        make_run(verdict=Verdict.INVALID, primary_failure=None),
        make_run(phase="confirm"),
        make_run(verdict=Verdict.PASS, primary_failure=None),
    ]
    matrix = FailureFeatureBuilder(FeatureWeights()).build(runs, space)  # type: ignore[arg-type]
    assert matrix.diagnostics.n_fail == 1
    assert matrix.diagnostics.n_excluded_invalid == 1
    assert matrix.diagnostics.n_input == 4


def test_missing_traj_zero_fill(space: object) -> None:
    run = make_run(metrics={})
    matrix = FailureFeatureBuilder(FeatureWeights()).build([run], space)  # type: ignore[arg-type]
    assert matrix.diagnostics.missing_traj is True
    n_cls = len(FailureClass)
    assert np.all(matrix.X[0, space.dim + n_cls :] == 0.0)  # type: ignore[union-attr]


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.integers(min_value=0, max_value=8))
def test_row_count_equals_fail_count(space: object, n_fail: int) -> None:
    runs = [make_run() for _ in range(n_fail)] + [
        make_run(verdict=Verdict.PASS, primary_failure=None)
    ]
    weights = FeatureWeights(param=2.0, class_=0.5, traj=0.25)
    matrix = FailureFeatureBuilder(weights).build(runs, space)  # type: ignore[arg-type]
    assert matrix.X.shape[0] == n_fail
    if n_fail:
        assert float(matrix.X.max()) <= max(weights.param, weights.class_, weights.traj) + 1e-12
        assert float(matrix.X.min()) >= 0.0
