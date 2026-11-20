"""Experiment comparison HTML report (docs/19 §7, docs/05 §12).

Implements: T-079, FR-EXP-003
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID

import numpy as np

from roboprobe.core.errors import NotFoundError
from roboprobe.core.seeding import ANALYSIS, derive_seed
from roboprobe.core.settings.experiments import ExperimentSettings
from roboprobe.core.settings.reporting import ReportingSettings
from roboprobe.core.types import JsonValue, Verdict
from roboprobe.experiments.runner import _as_campaign_row, build_comparison
from roboprobe.metrics.campaign_metrics import (
    CampaignRun,
    comparison_runs,
    FirstFailure,
    failure_discovery_rate,
    first_failure,
)
from roboprobe.metrics.statistics import effect_label
from roboprobe.reporting import figures
from roboprobe.reporting._env import template_env
from roboprobe.reporting.campaign import _css_block

__all__ = ["ExperimentReportContext", "render_experiment_report"]

_THREATS = (
    "Internal validity: comparability keys must match across strategies.",
    "Construct validity: robustness score may favour some failure classes.",
    "Statistical conclusion: few seeds limit power — report effect sizes.",
    "External validity: simulator backends may not reflect deployment hardware.",
)


class _UowPort(Protocol):
    experiments: Any
    campaigns: Any
    runs: Any


class _ArtifactPort(Protocol):
    def put(self, src: Path, kind: str, *, campaign_id: UUID | None = None) -> object: ...


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


def _campaign_runs(uow: _UowPort, campaign_id: UUID, budget: int) -> list[CampaignRun]:
    page = uow.runs.list_for_campaign(campaign_id, limit=None)
    rows = sorted(page.items, key=lambda r: (r.ordinal, r.repeat_index))
    out: list[CampaignRun] = []
    for row in rows:
        if row.verdict is None:
            continue
        verdict = Verdict(row.verdict) if not isinstance(row.verdict, Verdict) else row.verdict
        out.append(
            CampaignRun(
                verdict=verdict,
                wall_time_s=float((row.metrics or {}).get("duration_s", 0.0)),
                x_unit=tuple(float(x) for x in (row.x_unit or ())),
                phase=str(row.phase or ""),
                tags=tuple(str(t) for t in (row.tags or ())),
            )
        )
    _ = budget
    return out


def _variant_label(raw: object) -> str:
    tags = getattr(raw, "tags", ()) or ()
    for tag in tags:
        text = str(tag)
        if text.startswith("variant:"):
            return text[len("variant:") :]
    return str(getattr(raw, "strategy_id", ""))


def build_experiment_context(  # noqa: PLR0912, PLR0915
    experiment_id: UUID,
    uow: _UowPort,
    *,
    settings: ReportingSettings | None = None,
    experiment_settings: ExperimentSettings | None = None,
) -> ExperimentReportContext:
    """Build report view model, recomputing comparison when stored results exist."""
    cfg = settings or ReportingSettings()
    exp = uow.experiments.get(experiment_id)
    if exp is None:
        msg = "experiment not found"
        raise NotFoundError(msg, context={"experiment_id": str(experiment_id)})
    design = dict(exp.design) if isinstance(exp.design, dict) else {}
    results = dict(exp.results) if isinstance(exp.results, dict) else {}
    campaigns = list(uow.campaigns.list_for_experiment(experiment_id))
    rows = [_as_campaign_row(c) for c in campaigns]
    runs_by = {row.id: tuple(_campaign_runs(uow, row.id, row.budget)) for row in rows}
    metrics = [str(m) for m in design.get("metrics", ["MET-01", "MET-03"])]
    if not results:
        exp_cfg = experiment_settings or ExperimentSettings()
        seed = int((design.get("seeds") or {}).get("root", 0))
        rng = np.random.Generator(np.random.PCG64(derive_seed(seed, ANALYSIS, "compare")))
        results = build_comparison(
            experiment_id, rows, runs_by, metrics=metrics, settings=exp_cfg, rng=rng
        )
    strat_raw = results.get("strategies")
    strategies = (
        sorted(str(s) for s in cast(dict[str, object], strat_raw)) if isinstance(strat_raw, dict) else []
    )
    if not strategies:
        strategies = sorted({_variant_label(c) for c in campaigns})
    stats_rows: list[dict[str, str]] = []
    tests = results.get("tests") or []
    if isinstance(tests, list):
        for row in tests:
            if not isinstance(row, dict):
                continue
            a12_val = row.get("a12")
            effect = (
                str(effect_label(float(a12_val)))
                if isinstance(a12_val, (int, float))
                else "n/a"
            )
            stats_rows.append(
                {
                    "metric": str(row.get("metric", "")),
                    "a_vs_b": f"{row.get('a', '')} vs {row.get('b', '')}",
                    "p": str(row.get("p", "")),
                    "p_holm": str(row.get("p_holm", "")),
                    "a12": str(a12_val),
                    "effect": effect,
                }
            )
    boxplots: dict[str, str] = {}
    discovery_figures: dict[str, str] = {}
    km_inputs: dict[str, list[FirstFailure]] = {}
    strat_blocks = cast(dict[str, object], strat_raw) if isinstance(strat_raw, dict) else {}
    for metric in metrics:
        samples: dict[str, list[float]] = {s: [] for s in strategies}
        for label, block in strat_blocks.items():
            if not isinstance(block, dict):
                continue
            metric_block = cast(dict[str, object], block).get(metric)
            if not isinstance(metric_block, dict):
                continue
            samples[str(label)] = [float(metric_block.get("median", 0.0))]
        for row in rows:
            label = row.strategy_label
            runs = comparison_runs(runs_by.get(row.id, ()))
            if metric == "MET-01":
                fdr, _ = failure_discovery_rate(runs)
                samples.setdefault(label, []).append(float(fdr))
            elif metric == "MET-03":
                ff = first_failure(runs, budget=row.budget)
                samples.setdefault(label, []).append(float(ff.n1 + 1 if ff.censored else ff.n1))
                km_inputs.setdefault(label, []).append(ff)
            else:
                continue
        boxplots[metric] = figures.experiment_boxplot_svg(samples, metric=metric, settings=cfg)
    for label in strategies:
        curves: list[list[float]] = []
        for row in rows:
            if row.strategy_label != label:
                continue
            runs = comparison_runs(runs_by.get(row.id, ()))
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
    uow: _UowPort,
    store: _ArtifactPort,
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
