"""Matplotlib SVG figures for offline reports (docs/05 §12, docs/13).

Implements: T-078a, T-079, FR-DSH-007
"""

# ruff: noqa: PLC0415

from __future__ import annotations

from collections.abc import Mapping, Sequence
from io import StringIO
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np
import numpy.typing as npt

from roboprobe.core.settings.reporting import FigureSettings, ReportingSettings
from roboprobe.core.types import Verdict
from roboprobe.metrics.campaign_metrics import CampaignRun, FirstFailure
from roboprobe.reporting.theme import ReportTheme, load_theme, verdict_colour
from roboprobe.risk.mapper import REGION_FAILURE, REGION_SAFE, REGION_UNCERTAIN, RiskSlice
from roboprobe.risk.volume import RegionVolumes

if TYPE_CHECKING:
    import matplotlib.figure

class _ImportanceLike(Protocol):
    names: Sequence[str]
    mean_abs_shap: Sequence[float]


__all__ = [
    "discovery_curve_svg",
    "discovery_curve_with_ci_svg",
    "experiment_boxplot_svg",
    "importance_bars_svg",
    "interaction_heatmap_svg",
    "kaplan_meier_svg",
    "modes_bar_svg",
    "risk_slice_svg",
    "verdict_scatter_svg",
    "volume_bar_svg",
]

_SETTINGS = ReportingSettings()
_HASH_SALT = "roboprobe"
_NO_DATA = "No data"
_MARKERS = {Verdict.PASS: "o", Verdict.FAIL: "X", Verdict.INVALID: "D"}


def _figure_settings(settings: ReportingSettings | None) -> tuple[FigureSettings, ReportTheme]:
    cfg = settings or _SETTINGS
    return cfg.figures, load_theme(cfg.theme)


def _configure_mpl(theme: ReportTheme) -> None:
    import matplotlib as mpl

    mpl.use("Agg")
    mpl.rcParams.update(
        {
            "svg.hashsalt": _HASH_SALT,
            "svg.fonttype": "path",
            "figure.facecolor": theme.paper,
            "axes.facecolor": theme.paper_raised,
            "axes.edgecolor": theme.ink_muted,
            "axes.labelcolor": theme.ink,
            "text.color": theme.ink,
            "xtick.color": theme.ink_muted,
            "ytick.color": theme.ink_muted,
            "font.family": "sans-serif",
            "font.sans-serif": [theme.font_sans.replace("'", ""), "DejaVu Sans"],
        }
    )


def _import_plt() -> Any:  # noqa: ANN401
    import matplotlib.pyplot as plt

    return plt


def _fig_to_svg(fig: matplotlib.figure.Figure, *, settings: FigureSettings) -> str:
    buf = StringIO()
    fig.savefig(
        buf,
        format="svg",
        dpi=settings.dpi,
        bbox_inches="tight",
        metadata={"Date": None, "Creator": None},
    )
    fig.clear()
    return buf.getvalue()


def _placeholder_svg(message: str, *, settings: ReportingSettings | None = None) -> str:
    fig_cfg, theme = _figure_settings(settings)
    _configure_mpl(theme)
    plt = _import_plt()
    fig, ax = plt.subplots(figsize=(fig_cfg.width_in, fig_cfg.height_in))
    ax.set_axis_off()
    ax.text(
        0.5,
        0.5,
        message,
        ha="center",
        va="center",
        fontsize=12,
        color=theme.ink_muted,
        transform=ax.transAxes,
    )
    svg = _fig_to_svg(fig, settings=fig_cfg)
    plt.close(fig)
    return svg


def discovery_curve_svg(
    curve_y: Sequence[float],
    *,
    reference_band: tuple[Sequence[float], Sequence[float]] | None = None,
    x_label: str = "Proposal n",
    y_label: str = "Unique modes",
    settings: ReportingSettings | None = None,
) -> str:
    """Cumulative discovery curve as SVG."""
    if not curve_y:
        return _placeholder_svg(_NO_DATA, settings=settings)
    fig_cfg, theme = _figure_settings(settings)
    _configure_mpl(theme)
    plt = _import_plt()
    xs = np.arange(1, len(curve_y) + 1, dtype=np.float64)
    yy = np.asarray(curve_y, dtype=np.float64)
    fig, ax = plt.subplots(figsize=(fig_cfg.width_in, fig_cfg.height_in))
    if reference_band is not None:
        lo, hi = reference_band
        ax.fill_between(
            np.arange(1, len(lo) + 1, dtype=np.float64),
            lo,
            hi,
            color=theme.ink_muted,
            alpha=0.15,
            linewidth=0,
            label="reference band",
        )
    ax.plot(xs, yy, color=theme.accent, linewidth=2.0, marker=".", markersize=4)
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.grid(True, color=theme.ink_muted, alpha=0.15)
    if reference_band is not None:
        ax.legend(frameon=False, fontsize=9)
    svg = _fig_to_svg(fig, settings=fig_cfg)
    plt.close(fig)
    return svg


def discovery_curve_with_ci_svg(
    curves: Mapping[str, Sequence[Sequence[float]]],
    *,
    settings: ReportingSettings | None = None,
) -> str:
    """Mean discovery curve with bootstrap min/max bands per strategy."""
    if not curves or all(not v for v in curves.values()):
        return _placeholder_svg(_NO_DATA, settings=settings)
    fig_cfg, theme = _figure_settings(settings)
    _configure_mpl(theme)
    plt = _import_plt()
    fig, ax = plt.subplots(figsize=(fig_cfg.width_in, fig_cfg.height_in))
    colours = [theme.accent, theme.margin_line, theme.risk_uncertain, theme.risk_failure]
    for index, (label, series_list) in enumerate(curves.items()):
        arrays = [np.asarray(s, dtype=np.float64) for s in series_list if len(s)]
        if not arrays:
            continue
        max_len = max(a.size for a in arrays)
        mat = np.full((len(arrays), max_len), np.nan, dtype=np.float64)
        for row, arr in enumerate(arrays):
            mat[row, : arr.size] = arr
            if arr.size < max_len:
                mat[row, arr.size :] = arr[-1]
        mean = np.nanmean(mat, axis=0)
        lo = np.nanmin(mat, axis=0)
        hi = np.nanmax(mat, axis=0)
        xs = np.arange(1, max_len + 1, dtype=np.float64)
        colour = colours[index % len(colours)]
        ax.fill_between(xs, lo, hi, color=colour, alpha=0.2, linewidth=0)
        ax.plot(xs, mean, color=colour, label=label, linewidth=1.8)
    ax.set_xlabel("Proposal n")
    ax.set_ylabel("Unique modes")
    ax.legend(frameon=False, fontsize=9)
    ax.grid(True, color=theme.ink_muted, alpha=0.15)
    svg = _fig_to_svg(fig, settings=fig_cfg)
    plt.close(fig)
    return svg


def verdict_scatter_svg(  # noqa: PLR0913
    runs: Sequence[CampaignRun],
    x_index: int,
    y_index: int,
    *,
    x_name: str = "x",
    y_name: str = "y",
    settings: ReportingSettings | None = None,
) -> str:
    """Scatter of runs coloured by verdict (colour + marker, doc 13)."""
    plotted = [r for r in runs if len(r.x_unit) > max(x_index, y_index)]
    if not plotted:
        return _placeholder_svg(_NO_DATA, settings=settings)
    fig_cfg, theme = _figure_settings(settings)
    _configure_mpl(theme)
    plt = _import_plt()
    fig, ax = plt.subplots(figsize=(fig_cfg.width_in, fig_cfg.height_in))
    for verdict in (Verdict.PASS, Verdict.FAIL, Verdict.INVALID):
        subset = [r for r in plotted if r.verdict is verdict]
        if not subset:
            continue
        xs = [r.x_unit[x_index] for r in subset]
        ys = [r.x_unit[y_index] for r in subset]
        ax.scatter(
            xs,
            ys,
            c=verdict_colour(theme, verdict.value),
            marker=_MARKERS[verdict],
            s=36,
            linewidths=0.6,
            edgecolors=theme.ink,
            label=verdict.value,
        )
    ax.set_xlabel(x_name)
    ax.set_ylabel(y_name)
    ax.legend(frameon=False, fontsize=9, title="Verdict")
    ax.grid(True, color=theme.ink_muted, alpha=0.15)
    svg = _fig_to_svg(fig, settings=fig_cfg)
    plt.close(fig)
    return svg


def modes_bar_svg(
    modes: Sequence[tuple[str, int]],
    *,
    settings: ReportingSettings | None = None,
) -> str:
    """Bar chart of failure-mode sizes."""
    if not modes:
        return _placeholder_svg(_NO_DATA, settings=settings)
    fig_cfg, theme = _figure_settings(settings)
    _configure_mpl(theme)
    plt = _import_plt()
    labels = [code for code, _ in modes]
    sizes = [size for _, size in modes]
    fig, ax = plt.subplots(figsize=(fig_cfg.width_in, fig_cfg.height_in))
    ax.bar(labels, sizes, color=theme.accent, edgecolor=theme.ink_muted)
    ax.set_xlabel("Mode")
    ax.set_ylabel("Failures")
    ax.tick_params(axis="x", rotation=30)
    svg = _fig_to_svg(fig, settings=fig_cfg)
    plt.close(fig)
    return svg


def importance_bars_svg(
    report: _ImportanceLike | None,
    *,
    settings: ReportingSettings | None = None,
) -> str:
    """Horizontal SHAP mean-|value| bars."""
    if report is None or not report.names:
        return _placeholder_svg(_NO_DATA, settings=settings)
    fig_cfg, theme = _figure_settings(settings)
    _configure_mpl(theme)
    plt = _import_plt()
    names = list(report.names)
    values = list(report.mean_abs_shap)
    order = sorted(range(len(values)), key=lambda i: values[i])
    names = [names[i] for i in order]
    values = [values[i] for i in order]
    fig, ax = plt.subplots(figsize=(fig_cfg.width_in, fig_cfg.height_in))
    y_pos = np.arange(len(names), dtype=np.float64)
    ax.barh(y_pos, values, color=theme.accent, height=0.7)
    ax.set_yticks(y_pos, labels=names)
    ax.set_xlabel("Mean |SHAP|")
    ax.invert_yaxis()
    svg = _fig_to_svg(fig, settings=fig_cfg)
    plt.close(fig)
    return svg


def interaction_heatmap_svg(
    matrix: npt.NDArray[np.floating] | None,
    names: Sequence[str],
    *,
    settings: ReportingSettings | None = None,
) -> str:
    """Symmetric SHAP interaction strength heatmap."""
    if matrix is None or matrix.size == 0 or not names:
        return _placeholder_svg(_NO_DATA, settings=settings)
    fig_cfg, theme = _figure_settings(settings)
    _configure_mpl(theme)
    plt = _import_plt()
    data = np.asarray(matrix, dtype=np.float64)
    fig, ax = plt.subplots(figsize=(fig_cfg.width_in, fig_cfg.height_in))
    im = ax.imshow(data, cmap="Blues", aspect="auto")
    ax.set_xticks(range(len(names)), labels=names, rotation=45, ha="right")
    ax.set_yticks(range(len(names)), labels=names)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    svg = _fig_to_svg(fig, settings=fig_cfg)
    plt.close(fig)
    return svg


def risk_slice_svg(
    slice_: RiskSlice | None,
    *,
    settings: ReportingSettings | None = None,
) -> str:
    """Risk atlas slice with UNCERTAIN hatched (doc 13)."""
    if slice_ is None:
        return _placeholder_svg(_NO_DATA, settings=settings)
    fig_cfg, theme = _figure_settings(settings)
    _configure_mpl(theme)
    from matplotlib.colors import ListedColormap

    plt = _import_plt()
    colours = [theme.risk_safe, theme.risk_uncertain, theme.risk_failure]
    cmap = ListedColormap(colours)
    fig, ax = plt.subplots(figsize=(fig_cfg.width_in, fig_cfg.height_in))
    mesh = ax.pcolormesh(
        slice_.x_values,
        slice_.y_values,
        slice_.region.T,
        cmap=cmap,
        vmin=REGION_SAFE,
        vmax=REGION_FAILURE,
        shading="auto",
    )
    uncertain = slice_.region == REGION_UNCERTAIN
    if np.any(uncertain):
        yy, xx = np.meshgrid(slice_.y_values, slice_.x_values, indexing="ij")
        ax.contourf(
            xx,
            yy,
            uncertain.astype(np.float64),
            levels=[0.5, 1.5],
            colors=["none"],
            hatches=["//"],
            alpha=0.0,
        )
    _ = mesh
    ax.set_xlabel(slice_.x_param)
    ax.set_ylabel(slice_.y_param)
    ax.set_title(f"{slice_.x_param} x {slice_.y_param}")
    svg = _fig_to_svg(fig, settings=fig_cfg)
    plt.close(fig)
    return svg


def volume_bar_svg(
    volumes: RegionVolumes | Mapping[str, float] | None,
    *,
    settings: ReportingSettings | None = None,
) -> str:
    """SAFE / UNCERTAIN / FAILURE volume fractions."""
    if volumes is None:
        return _placeholder_svg(_NO_DATA, settings=settings)
    fig_cfg, theme = _figure_settings(settings)
    _configure_mpl(theme)
    plt = _import_plt()
    if isinstance(volumes, RegionVolumes):
        labels = ["SAFE", "UNCERTAIN", "FAILURE"]
        values = [volumes.safe, volumes.uncertain, volumes.failure]
        colours = [theme.risk_safe, theme.risk_uncertain, theme.risk_failure]
    else:
        labels = list(volumes.keys())
        values = [float(volumes[k]) for k in labels]
        palette = [theme.risk_safe, theme.risk_uncertain, theme.risk_failure, theme.accent]
        colours = [palette[i % len(palette)] for i in range(len(labels))]
    fig, ax = plt.subplots(figsize=(fig_cfg.width_in, fig_cfg.height_in))
    ax.bar(labels, values, color=colours, edgecolor=theme.ink_muted)
    ax.set_ylabel("Volume fraction")
    ax.set_ylim(0.0, 1.0)
    svg = _fig_to_svg(fig, settings=fig_cfg)
    plt.close(fig)
    return svg


def experiment_boxplot_svg(
    samples: Mapping[str, Sequence[float]],
    *,
    metric: str,
    settings: ReportingSettings | None = None,
) -> str:
    """Per-strategy box plots for one metric."""
    if not samples or all(len(v) == 0 for v in samples.values()):
        return _placeholder_svg(_NO_DATA, settings=settings)
    fig_cfg, theme = _figure_settings(settings)
    _configure_mpl(theme)
    plt = _import_plt()
    labels = list(samples.keys())
    data = [list(samples[label]) for label in labels]
    fig, ax = plt.subplots(figsize=(fig_cfg.width_in, fig_cfg.height_in))
    bp = ax.boxplot(data, tick_labels=labels, patch_artist=True)
    for patch in bp["boxes"]:
        patch.set_facecolor(theme.accent)
        patch.set_alpha(0.35)
    ax.set_title(metric)
    ax.set_ylabel("Value")
    ax.grid(True, axis="y", color=theme.ink_muted, alpha=0.15)
    svg = _fig_to_svg(fig, settings=fig_cfg)
    plt.close(fig)
    return svg


def kaplan_meier_svg(
    failures: Mapping[str, Sequence[FirstFailure]],
    *,
    budget: int,
    settings: ReportingSettings | None = None,
) -> str:
    """Kaplan-Meier step curves for MET-03 (censored at budget)."""
    if not failures or all(len(v) == 0 for v in failures.values()):
        return _placeholder_svg(_NO_DATA, settings=settings)
    fig_cfg, theme = _figure_settings(settings)
    _configure_mpl(theme)
    plt = _import_plt()
    fig, ax = plt.subplots(figsize=(fig_cfg.width_in, fig_cfg.height_in))
    colours = [theme.accent, theme.margin_line, theme.risk_uncertain, theme.risk_failure]
    for index, (label, entries) in enumerate(failures.items()):
        if not entries:
            continue
        times = sorted(
            int(e.n1 if not e.censored else budget) for e in entries
        )
        colour = colours[index % len(colours)]
        xs = [0]
        ys = [1.0]
        at_risk = len(times)
        for t in range(1, budget + 1):
            events = sum(1 for v in times if v == t)
            if events:
                surv = ys[-1] * (at_risk - events) / at_risk if at_risk else ys[-1]
                at_risk -= events
                xs.append(t)
                ys.append(surv)
            elif t == budget:
                xs.append(t)
                ys.append(ys[-1])
        ax.step(xs, ys, where="post", color=colour, label=label, linewidth=1.8)
    ax.set_xlabel("Proposal n")
    ax.set_ylabel("P(no failure yet)")
    ax.set_ylim(0.0, 1.05)
    ax.legend(frameon=False, fontsize=9)
    ax.grid(True, color=theme.ink_muted, alpha=0.15)
    svg = _fig_to_svg(fig, settings=fig_cfg)
    plt.close(fig)
    return svg
