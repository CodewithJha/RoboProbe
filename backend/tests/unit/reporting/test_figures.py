"""Matplotlib SVG figure tests (T-078a)."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import numpy as np
import pytest

from roboprobe.core.types import Verdict
from roboprobe.metrics.campaign_metrics import CampaignRun, FirstFailure
from roboprobe.reporting import figures
from roboprobe.risk.mapper import REGION_FAILURE, REGION_SAFE, REGION_UNCERTAIN, RiskSlice
from roboprobe.risk.volume import RegionVolumes

pytestmark = pytest.mark.unit


def _is_svg(text: str) -> bool:
    head = text.lstrip()
    return head.startswith("<svg") or head.startswith("<?xml")


def test_discovery_curve_svg_valid_and_deterministic() -> None:
    y = [0.0, 1.0, 1.0, 2.0]
    a = figures.discovery_curve_svg(y)
    b = figures.discovery_curve_svg(y)
    assert _is_svg(a)
    assert hashlib.sha256(a.encode()).hexdigest() == hashlib.sha256(b.encode()).hexdigest()


def test_discovery_curve_empty_placeholder() -> None:
    svg = figures.discovery_curve_svg([])
    assert _is_svg(svg)
    assert "No data" in svg


def test_verdict_scatter_and_modes_bar() -> None:
    runs = [
        CampaignRun(Verdict.PASS, 1.0, x_unit=(0.2, 0.3)),
        CampaignRun(Verdict.FAIL, 2.0, x_unit=(0.5, 0.7)),
        CampaignRun(Verdict.INVALID, 0.5, x_unit=(0.1, 0.9)),
    ]
    assert _is_svg(figures.verdict_scatter_svg(runs, 0, 1))
    assert _is_svg(figures.modes_bar_svg([("M-01", 3), ("M-02", 1)]))


def test_importance_and_interaction() -> None:
    report = SimpleNamespace(
        names=("a", "b"),
        mean_abs_shap=(0.2, 0.5),
        interactions=((0.0, 0.1), (0.1, 0.0)),
    )
    assert _is_svg(figures.importance_bars_svg(report))
    assert _is_svg(figures.interaction_heatmap_svg(np.asarray(report.interactions), report.names))


def test_risk_slice_and_volume() -> None:
    xs = np.linspace(0, 1, 4)
    ys = np.linspace(0, 1, 4)
    grid = np.zeros((4, 4), dtype=np.int8)
    grid[0, 0] = REGION_SAFE
    grid[1, 1] = REGION_UNCERTAIN
    grid[2, 2] = REGION_FAILURE
    sl = RiskSlice(
        x_param="x",
        y_param="y",
        x_values=xs,
        y_values=ys,
        log_x=False,
        log_y=False,
        p_fail=np.zeros((4, 4)),
        mean=np.zeros((4, 4)),
        std=np.ones((4, 4)),
        region=grid,
        anchor={},
        grid_u=np.zeros((16, 2)),
    )
    assert _is_svg(figures.risk_slice_svg(sl))
    vol = RegionVolumes(
        safe=0.5,
        uncertain=0.3,
        failure=0.2,
        safe_ci=(0.4, 0.6),
        uncertain_ci=(0.2, 0.4),
        failure_ci=(0.1, 0.3),
        n=1024,
        seed=1,
    )
    assert _is_svg(figures.volume_bar_svg(vol))


def test_experiment_figures() -> None:
    samples = {"S-RANDOM": [0.1, 0.2], "S-PROBE": [0.3, 0.4, 0.5]}
    assert _is_svg(figures.experiment_boxplot_svg(samples, metric="MET-01"))
    failures = {
        "S-RANDOM": [FirstFailure(3, False), FirstFailure(5, True)],
        "S-PROBE": [FirstFailure(2, False)],
    }
    assert _is_svg(figures.kaplan_meier_svg(failures, budget=10))
