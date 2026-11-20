"""Hand-computed discovery metrics MET-02/04/08/09 (T-100b)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from roboprobe.core.settings.experiments import ExperimentSettings
from roboprobe.core.types import Verdict
from roboprobe.metrics.campaign_metrics import CampaignRun
from roboprobe.metrics.discovery_metrics import (
    NOVEL_LABEL,
    P_FAIL_THRESHOLD,
    bin_coverage_c2,
    boundary_accuracy,
    comparison_unit_points,
    discovery_auc,
    discovery_curve,
    failing_unit_points,
    failure_region_coverage,
    label_failures,
    pooled_cluster_hits,
    unique_gt_modes,
)

pytestmark = pytest.mark.unit
SETTINGS = ExperimentSettings()


def _fail(x: tuple[float, ...]) -> CampaignRun:
    return CampaignRun(verdict=Verdict.FAIL, wall_time_s=1.0, x_unit=x)


def _pass(x: tuple[float, ...]) -> CampaignRun:
    return CampaignRun(verdict=Verdict.PASS, wall_time_s=1.0, x_unit=x)


def test_mode_match_radius_and_bins_from_settings() -> None:
    assert SETTINGS.mode_match_radius == pytest.approx(0.05)
    assert SETTINGS.coverage_bins == 5
    assert pytest.approx(0.5) == P_FAIL_THRESHOLD


def test_unique_gt_modes_nearest_within_radius() -> None:
    ref = np.array([[0.0, 0.0], [1.0, 0.0]])
    labels = ["GT-A", "GT-B"]
    runs = [_fail((0.01, 0.0)), _pass((0.5, 0.5)), _fail((0.5, 0.5))]
    # (0.01,0) → GT-A; (0.5,0.5) is > r from both → novel. Unique GT = 1.
    assert (
        unique_gt_modes(failing_unit_points(runs), ref, labels, radius=SETTINGS.mode_match_radius)
        == 1
    )
    assert label_failures([(0.5, 0.5)], ref, labels, radius=0.05) == [NOVEL_LABEL]


def test_unique_gt_modes_hits_two_and_empty() -> None:
    ref = np.array([[0.0, 0.0], [1.0, 0.0]])
    labels = ["GT-A", "GT-B"]
    runs = [_fail((0.0, 0.0)), _fail((0.99, 0.0)), _fail((0.0, 0.0))]
    assert unique_gt_modes(failing_unit_points(runs), ref, labels) == 2
    assert unique_gt_modes(failing_unit_points([]), ref, labels) == 0
    assert unique_gt_modes(failing_unit_points([_pass((0.0, 0.0))]), ref, labels) == 0


def test_pooled_cluster_hits_radius_graph() -> None:
    hits = pooled_cluster_hits(
        {
            "S-PROBE": np.array([[0.0, 0.0], [0.01, 0.0]]),
            "S-RANDOM": np.array([[0.005, 0.0], [0.9, 0.9]]),
        },
        radius=0.05,
    )
    # {0, 0.01, 0.005} one component; {0.9,0.9} another. PROBE hits 1, RANDOM hits 2.
    assert hits["S-PROBE"] == 1
    assert hits["S-RANDOM"] == 2


def test_pooled_cluster_hits_supplied_labels_and_empty() -> None:
    hits = pooled_cluster_hits(
        {"A": [[0.0, 0.0]], "B": [[1.0, 1.0]]},
        labels=[0, 0],
    )
    assert hits == {"A": 1, "B": 1}
    empty = pooled_cluster_hits({"A": np.empty((0, 2)), "B": np.empty((0, 2))})
    assert empty == {"A": 0, "B": 0}


def test_bin_coverage_c2_two_dims_two_bins() -> None:
    points = np.array([[0.1, 0.1], [0.6, 0.1]])
    # C(2,2)=1 pair, k=2 → 4 cells; bins (0,0) and (1,0) → C2 = 2/4
    assert bin_coverage_c2(points, k=2) == pytest.approx(0.5)
    assert math.isnan(bin_coverage_c2(np.empty((0, 2)), k=2))
    assert math.isnan(bin_coverage_c2(np.array([[0.1]]), k=2))


def test_bin_coverage_excludes_confirm() -> None:
    runs = [
        _pass((0.1, 0.1)),
        CampaignRun(verdict=Verdict.FAIL, wall_time_s=1.0, x_unit=(0.9, 0.9), phase="confirm"),
    ]
    assert bin_coverage_c2(comparison_unit_points(runs), k=2) == pytest.approx(0.25)


def test_failure_region_coverage() -> None:
    ref_fail = np.array([[0.0, 0.0], [1.0, 1.0], [0.02, 0.0]])
    runs = [_fail((0.0, 0.0))]
    # two of three ref points within 0.05 of (0,0)
    assert failure_region_coverage(
        failing_unit_points(runs), ref_fail, radius=0.05
    ) == pytest.approx(2 / 3)
    assert failure_region_coverage(failing_unit_points([]), ref_fail) == 0.0
    assert math.isnan(failure_region_coverage(failing_unit_points(runs), np.empty((0, 2))))


def test_boundary_accuracy_perfect_and_edges() -> None:
    p = [0.9, 0.1, 0.8, 0.2]
    y = [True, False, True, False]
    bal, rec, f1 = boundary_accuracy(p, y)
    assert (bal, rec, f1) == pytest.approx((1.0, 1.0, 1.0))
    # no predicted failures: recall 0, precision nan → f1 nan; TNR=1, TPR=0 → bal=0.5
    bal2, rec2, f1_2 = boundary_accuracy([0.1, 0.1], [True, False])
    assert rec2 == 0.0
    assert bal2 == pytest.approx(0.5)
    assert math.isnan(f1_2)
    assert all(math.isnan(v) for v in boundary_accuracy([], []))


def test_discovery_curve_monotone_and_auc() -> None:
    labels = ["GT-A", None, "GT-B", None, "GT-A"]
    curve = discovery_curve(labels, n_gt=2)
    np.testing.assert_array_equal(curve, [1.0, 1.0, 2.0, 2.0, 2.0])
    assert np.all(np.diff(curve) >= 0)
    # AUC = (1/5) Σ modes(n)/2 = (1+1+2+2+2)/(5*2) = 0.8
    assert discovery_auc(labels, n_gt=2) == pytest.approx(0.8)
    # pad budget 7 holds last value: extra 2/2 twice → (8+2+2)/(7*2)=12/14
    assert discovery_auc(labels, n_gt=2, budget=7) == pytest.approx(12 / 14)
    assert math.isnan(discovery_auc(labels, n_gt=0))
    assert math.isnan(discovery_auc([], n_gt=2, budget=0))
