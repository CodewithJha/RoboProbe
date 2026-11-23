"""Experiment comparison HTML report (docs/19 §7, docs/05 §12).

Implements: T-079, FR-EXP-003
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import cast
from uuid import UUID

from roboprobe.core.errors import NotFoundError
from roboprobe.core.settings.experiments import ExperimentSettings
from roboprobe.core.settings.reporting import ReportingSettings
from roboprobe.core.types import JsonValue, Verdict
from roboprobe.experiments.comparison import read_campaign_runs, resolve_comparison
from roboprobe.experiments.runner import (
    _as_campaign_row,
    _metric_value,
    analytic_ground_truth,
    analytic_mode_labels,
)
from roboprobe.metrics.campaign_metrics import (
    FirstFailure,
    comparison_runs,
    failure_discovery_rate,
    first_failure,
)
from roboprobe.metrics.discovery_metrics import discovery_curve
from roboprobe.reporting import figures
from roboprobe.reporting._env import template_env
from roboprobe.reporting.campaign import _css_block
from roboprobe.reporting.ports import ReportArtifactStore, ReportUnitOfWork

__all__ = ["ExperimentReportContext", "render_experiment_report"]

_THREATS = (
    "Internal validity: comparability keys must match across strategies.",
    "Construct validity: robustness score may favour some failure classes.",
    "Statistical conclusion: few seeds limit power — report effect sizes.",
    "External validity: simulator backends may not reflect deployment hardware.",
)


@dataclass(frozen=True, slots=True)
class ExperimentReportContext:
    """View model for experiment HTML templates."""

    experiment_id: UUID
    title: str
    design_rows: list[tuple[str, str]]
    strategies: list[str]
    metrics: list[str]
    stats_rows: list[dict[str, str]]
    boxplots: dict[str, str]
    discovery_figures: dict[str, str]
    km_figure: str
    threats: tuple[str, ...]
    comparison: dict[str, JsonValue]
    css: str


def build_experiment_context(  # noqa: PLR0912, PLR0915
    experiment_id: UUID,
    uow: ReportUnitOfWork,
    *,
    settings: ReportingSettings | None = None,
    experiment_settings: ExperimentSettings | None = None,
) -> ExperimentReportContext:
    """Build the HTML view with the same comparison data as the API."""
    cfg = settings or ReportingSettings()
    exp = uow.experiments.get(experiment_id)
    if exp is None:
        msg = "experiment not found"
        raise NotFoundError(msg, context={"experiment_id": str(experiment_id)})
    design = dict(exp.design) if isinstance(exp.design, dict) else {}
    ground_truth = analytic_ground_truth(design)
    rows = [_as_campaign_row(row) for row in uow.campaigns.list_for_experiment(experiment_id)]
    runs_by = {row.id: read_campaign_runs(uow.runs, row.id) for row in rows}
    results = resolve_comparison(
        experiment_id, exp, rows, runs_by, experiment_settings or ExperimentSettings()
    )
    metrics = [
        metric for metric in cast(list[JsonValue], results["metrics"]) if isinstance(metric, str)
    ]
    strategies = sorted(cast(dict[str, JsonValue], results["strategies"]))
    stats_rows: list[dict[str, str]] = []
    tests = results.get("tests") or []
    if isinstance(tests, list):
        for test in tests:
            if not isinstance(test, dict):
                continue
            a12_val = test.get("a12")
            stats_rows.append(
                {
                    "metric": str(test.get("metric", "")),
                    "a_vs_b": f"{test.get('a', '')} vs {test.get('b', '')}",
                    "p": str(test.get("p", "")),
                    "p_holm": str(test.get("p_holm", "")),
                    "a12": str(a12_val),
                    "effect": str(test.get("effect") or "n/a"),
                }
            )
    boxplots: dict[str, str] = {}
    discovery_figures: dict[str, str] = {}
    km_inputs: dict[str, list[FirstFailure]] = {}
    for metric in metrics:
        samples: dict[str, list[float]] = {strategy: [] for strategy in strategies}
        for row in rows:
            label = row.strategy_label
            runs = comparison_runs(runs_by.get(row.id, ()))
            if not runs:
                continue
            if metric == "MET-01":
                fdr, _ = failure_discovery_rate(runs)
                if isfinite(fdr):
                    samples.setdefault(label, []).append(fdr)
            elif metric == "MET-03":
                ff = first_failure(runs, budget=row.budget)
                samples.setdefault(label, []).append(float(ff.n1 + 1 if ff.censored else ff.n1))
                km_inputs.setdefault(label, []).append(ff)
            elif ground_truth is not None and metric in {"MET-02", "MET-09"}:
                samples.setdefault(label, []).append(
                    _metric_value(metric, runs, row.budget, ground_truth)
                )
            else:
                continue
        boxplots[metric] = figures.experiment_boxplot_svg(samples, metric=metric, settings=cfg)
    for label in strategies:
        curves: list[list[float]] = []
        for row in rows:
            if row.strategy_label != label:
                continue
            runs = comparison_runs(runs_by.get(row.id, ()))
            if ground_truth is not None:
                cumulative = discovery_curve(
                    analytic_mode_labels(runs, ground_truth), ground_truth.n_modes
                ).tolist()
            else:
                fails = [1.0 if r.verdict is Verdict.FAIL else 0.0 for r in runs]
                cumulative = [float(sum(fails[: i + 1])) for i in range(len(fails))]
            if cumulative:
                curves.append(cumulative)
        if curves:
            discovery_figures[label] = figures.discovery_curve_with_ci_svg(
                {label: curves}, settings=cfg
            )
    budget = int(design.get("budget", rows[0].budget if rows else 1))
    km_figure = figures.kaplan_meier_svg(km_inputs, budget=budget, settings=cfg)
    design_rows = [
        ("Experiment", str(exp.name)),
        ("ID", str(experiment_id)),
        ("Backend", str(design.get("backend", ""))),
        ("Budget", str(design.get("budget", ""))),
        ("Metrics", ", ".join(metrics)),
        ("Strategies", ", ".join(strategies)),
    ]
    return ExperimentReportContext(
        experiment_id=experiment_id,
        title=str(exp.name),
        design_rows=design_rows,
        strategies=strategies,
        metrics=metrics,
        stats_rows=stats_rows,
        boxplots=boxplots,
        discovery_figures=discovery_figures,
        km_figure=km_figure,
        threats=_THREATS,
        comparison=results,
        css=_css_block(cfg),
    )


def render_experiment_report(  # noqa: PLR0913
    experiment_id: UUID,
    uow: ReportUnitOfWork,
    store: ReportArtifactStore,
    *,
    out: Path | None = None,
    settings: ReportingSettings | None = None,
    experiment_settings: ExperimentSettings | None = None,
) -> Path:
    """Render experiment HTML report to ``out`` (docs/05 §12)."""
    ctx = build_experiment_context(
        experiment_id, uow, settings=settings, experiment_settings=experiment_settings
    )
    env = template_env()
    template = env.get_template("experiment/report.html.j2")
    html = template.render(context=ctx)
    if out is None:
        fd, name = tempfile.mkstemp(suffix=".html", prefix="roboprobe-experiment-")
        os.close(fd)
        dest = Path(name)
    else:
        dest = out
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html, encoding="utf-8")
    store.put(dest, kind="report", campaign_id=None)
    return dest
