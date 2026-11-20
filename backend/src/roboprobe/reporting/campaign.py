"""Campaign HTML report renderer (docs/05 §12, docs/13 §3.9).

Implements: T-078b, FR-DSH-007
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import numpy as np

from roboprobe.core.errors import NotFoundError
from roboprobe.core.settings.reporting import ReportingSettings
from roboprobe.core.types import Verdict
from roboprobe.metrics.campaign_metrics import CampaignRun, comparison_runs, first_failure
from roboprobe.metrics.discovery_metrics import discovery_curve
from roboprobe.reporting import figures
from roboprobe.reporting._env import template_env
from roboprobe.reporting.figures import _ImportanceLike
from roboprobe.reporting.ports import ReportArtifactStore, ReportUnitOfWork
from roboprobe.reporting.theme import load_theme, tokens_path
from roboprobe.risk.mapper import RiskSlice, load_slices
from roboprobe.risk.volume import RegionVolumes, robustness_score

__all__ = ["CampaignReportContext", "render_campaign_report"]


@dataclass(frozen=True, slots=True)
class CampaignReportContext:
    """View model passed to Jinja templates."""

    campaign_id: UUID
    title: str
    config_rows: list[tuple[str, str]]
    counts: dict[str, int]
    discovery_svg: str
    verdict_svg: str
    modes_svg: str
    importance_svg: str
    interaction_svg: str
    slice_svgs: list[str]
    volume_svg: str
    robustness: float | None
    modes: list[dict[str, Any]]
    importance_low_confidence: bool
    appendix_runs: list[dict[str, str]]
    warnings: list[str]
    css: str


def _css_block(settings: ReportingSettings) -> str:
    theme = load_theme(settings.theme)
    raw = json.loads(tokens_path().read_text(encoding="utf-8"))
    vars_light = raw["light"]
    font = raw["font"]
    space = raw["space"]
    radius = raw["radius"]
    lines = [
        ":root {",
        *(f"  {k}: {v};" for k, v in vars_light.items()),
        *(f"  {k}: {v};" for k, v in font.items()),
        *(f"  {k}: {v};" for k, v in space.items()),
        *(f"  {k}: {v};" for k, v in radius.items()),
        "  --ink: " + theme.ink + ";",
        "}",
    ]
    css_path = Path(__file__).resolve().parent / "assets" / "report.css"
    return "\n".join(lines) + "\n" + css_path.read_text(encoding="utf-8")


def _runs_from_uow(uow: ReportUnitOfWork, campaign_id: UUID) -> list[CampaignRun]:
    page = uow.runs.list_for_campaign(campaign_id, limit=None)
    rows = sorted(page.items, key=lambda r: (r.ordinal, r.repeat_index))
    out: list[CampaignRun] = []
    for row in rows:
        if row.verdict is None:
            continue
        verdict = row.verdict if isinstance(row.verdict, Verdict) else Verdict(str(row.verdict))
        duration = (row.metrics or {}).get("duration_s", 0.0)
        out.append(
            CampaignRun(
                verdict=verdict,
                wall_time_s=float(cast(float | int | str, duration)),
                x_unit=tuple(float(x) for x in (row.x_unit or ())),
                phase=str(row.phase or ""),
                tags=tuple(str(t) for t in (row.tags or ())),
            )
        )
    return out


def _discovery_series(mode_labels: Sequence[str | None]) -> list[float]:
    if mode_labels:
        curve = discovery_curve(mode_labels, n_gt=max(1, len({m for m in mode_labels if m})))
        return [float(y) for y in curve]
    return []


def _importance_from_summary(summary: Mapping[str, Any]) -> object | None:
    imp = summary.get("importance_full")
    if not isinstance(imp, dict):
        return None
    try:
        types = __import__("roboprobe.analysis.types", fromlist=["ImportanceReport"])
        validated = types.ImportanceReport.model_validate(imp)
        return cast(_ImportanceLike, validated)
    except Exception:
        return None


def _volumes_from_summary(summary: Mapping[str, Any]) -> RegionVolumes | None:
    vol = summary.get("volumes")
    if not isinstance(vol, dict):
        return None
    try:
        return RegionVolumes(
            safe=float(vol["safe"]),
            uncertain=float(vol["uncertain"]),
            failure=float(vol["failure"]),
            safe_ci=tuple(vol.get("safe_ci", (0.0, 0.0))),
            uncertain_ci=tuple(vol.get("uncertain_ci", (0.0, 0.0))),
            failure_ci=tuple(vol.get("failure_ci", (0.0, 0.0))),
            n=int(vol.get("n", 0)),
            seed=int(vol.get("seed", 0)),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _load_slices_from_store(
    store: ReportArtifactStore, uow: ReportUnitOfWork, campaign_id: UUID
) -> list[RiskSlice]:
    latest = uow.risk_maps.latest(campaign_id)
    if latest is None or latest.slices_artifact is None:
        return []
    row = uow.artifacts.get(latest.slices_artifact)
    if row is None:
        return []
    ref = SimpleNamespace(sha256=str(row.sha256), rel_path=str(row.rel_path))
    try:
        blob = store.path(ref)
    except Exception:
        return []
    if not Path(blob).is_file():
        return []
    return load_slices(Path(blob))


def build_campaign_context(  # noqa: PLR0915
    campaign_id: UUID,
    uow: ReportUnitOfWork,
    store: ReportArtifactStore,
    *,
    settings: ReportingSettings | None = None,
) -> CampaignReportContext:
    """Assemble template context from persistence ports."""
    cfg = settings or ReportingSettings()
    campaign = uow.campaigns.get(campaign_id)
    if campaign is None:
        msg = "campaign not found"
        raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
    runs = _runs_from_uow(uow, campaign_id)
    cmp_runs = comparison_runs(runs)
    analyses = uow.analyses.list_for_campaign(campaign_id)
    latest = analyses[-1] if analyses else None
    summary: dict[str, Any] = dict(latest.summary) if latest is not None else {}
    warnings = list(summary.get("warnings", []))
    mode_rows = list(uow.modes.list_for_campaign(campaign_id))
    modes_payload: list[dict[str, Any]] = []
    for mode in mode_rows:
        rule_text = ""
        if mode.rules:
            first = mode.rules[0]
            rule_text = str(first.get("text", "")) if isinstance(first, dict) else ""
        interaction = mode.interaction or {}
        modes_payload.append(
            {
                "code": mode.code,
                "label": mode.label,
                "size": mode.size,
                "primary_class": mode.primary_class,
                "class_mix": mode.class_mix,
                "rule": rule_text,
                "interaction_status": str(interaction.get("status", "")),
                "medoid_run_id": str(mode.medoid_run_id) if mode.medoid_run_id else "",
                "minimal_run_id": str(mode.minimal_run_id) if mode.minimal_run_id else "",
            }
        )
    mode_labels_raw = summary.get("discovery_mode_labels")
    labels: list[str | None] = []
    if isinstance(mode_labels_raw, list):
        labels = [None if x is None else str(x) for x in mode_labels_raw]
    elif mode_rows:
        labels = [None] * len(cmp_runs)
    discovery = (
        _discovery_series(labels)
        if labels
        else [
            float(sum(1 for r in cmp_runs[: i + 1] if r.verdict is Verdict.FAIL))
            for i in range(len(cmp_runs))
        ]
    )
    x_idx, y_idx = 0, 1 if any(len(r.x_unit) > 1 for r in runs) else 0
    importance = _importance_from_summary(summary)
    interaction_names = list(getattr(importance, "names", ())) if importance else []
    interactions = getattr(importance, "interactions", ()) if importance else ()
    interaction_matrix = None if not interactions else [list(row) for row in interactions]
    volumes = _volumes_from_summary(summary)
    slices = _load_slices_from_store(store, uow, campaign_id)
    slice_svgs = [figures.risk_slice_svg(s, settings=cfg) for s in slices[:4]]
    vol_map = summary.get("volumes") if isinstance(summary.get("volumes"), dict) else None
    robust = None
    if volumes is not None:
        robust = robustness_score(volumes)
    elif vol_map is not None and "robustness_score" in vol_map:
        try:
            robust = float(vol_map["robustness_score"])
        except (TypeError, ValueError):
            robust = None
    counts = {
        "total": len(runs),
        "pass": sum(1 for r in runs if r.verdict is Verdict.PASS),
        "fail": sum(1 for r in runs if r.verdict is Verdict.FAIL),
        "invalid": sum(1 for r in runs if r.verdict is Verdict.INVALID),
    }
    ff = first_failure(cmp_runs, budget=int(campaign.budget))
    config = [
        ("Campaign", str(campaign.name)),
        ("ID", str(campaign_id)),
        ("Backend", str(campaign.backend)),
        ("Strategy", str(campaign.strategy_id)),
        ("Budget", str(campaign.budget)),
        ("Seed", str(campaign.seed)),
        (
            "First failure (MET-03)",
            str(ff.n1 if not ff.censored else f">{campaign.budget} (censored)"),
        ),
    ]
    appendix: list[dict[str, str]] = []
    seen: set[UUID] = set()
    page = uow.runs.list_for_campaign(campaign_id, limit=None)
    for row in page.items:
        if row.id in seen:
            continue
        seen.add(row.id)
        appendix.append(
            {
                "run_id": str(row.id),
                "manifest_sha256": str(getattr(row, "manifest_sha256", "") or ""),
                "ordinal": str(row.ordinal),
                "verdict": str(row.verdict or ""),
            }
        )
    return CampaignReportContext(
        campaign_id=campaign_id,
        title=str(campaign.name),
        config_rows=config,
        counts=counts,
        discovery_svg=figures.discovery_curve_svg(discovery, settings=cfg),
        verdict_svg=figures.verdict_scatter_svg(
            runs, x_idx, y_idx, x_name="param 0", y_name="param 1", settings=cfg
        ),
        modes_svg=figures.modes_bar_svg(
            [(m["code"], int(m["size"])) for m in modes_payload], settings=cfg
        ),
        importance_svg=figures.importance_bars_svg(
            cast(_ImportanceLike, importance) if importance is not None else None,
            settings=cfg,
        ),
        interaction_svg=figures.interaction_heatmap_svg(
            None
            if interaction_matrix is None
            else np.asarray(interaction_matrix, dtype=np.float64),
            interaction_names,
            settings=cfg,
        ),
        slice_svgs=slice_svgs,
        volume_svg=figures.volume_bar_svg(volumes or vol_map, settings=cfg),
        robustness=robust,
        modes=modes_payload,
        importance_low_confidence=bool(
            getattr(importance, "low_confidence", False)
            if importance is not None
            else (summary.get("importance") or {}).get("low_confidence", False)
        ),
        appendix_runs=appendix,
        warnings=warnings,
        css=_css_block(cfg),
    )


def render_campaign_report(
    campaign_id: UUID,
    uow: ReportUnitOfWork,
    store: ReportArtifactStore,
    *,
    out: Path | None = None,
    settings: ReportingSettings | None = None,
) -> Path:
    """Render a self-contained campaign HTML report (docs/05 §12).

    Args:
        campaign_id: Campaign to describe.
        uow: Unit of work exposing campaign/run/mode repositories.
        store: Artefact store for slice blobs and report archival.
        out: Optional destination path; otherwise a temp file is used.
        settings: Figure and theme settings.

    Returns:
        Path to the written HTML file.
    """
    ctx = build_campaign_context(campaign_id, uow, store, settings=settings)
    env = template_env()
    template = env.get_template("campaign/report.html.j2")
    html = template.render(context=ctx)
    if out is None:
        fd, name = tempfile.mkstemp(suffix=".html", prefix="roboprobe-campaign-")
        os.close(fd)
        dest = Path(name)
    else:
        dest = out
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html, encoding="utf-8")
    store.put(dest, kind="report", campaign_id=campaign_id)
    return dest
