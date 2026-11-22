"""Campaign analysis pipeline: pluggable steps, artefacts and persistence (docs/09 §8).

Implements: T-075a, FR-ANA-006
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import logging
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Final, cast
from uuid import UUID, uuid4

import numpy as np
import numpy.typing as npt
import pyarrow as pa
import pyarrow.parquet as pq

from roboprobe.analysis.base import (
    AnalysisContext,
    AnalysisKind,
    AnalysisReport,
    Analyzer,
)
from roboprobe.analysis.clustering import FailureClusterer
from roboprobe.analysis.features import FailureFeatureBuilder
from roboprobe.analysis.importance import ImportanceExplainer
from roboprobe.analysis.mode_matching import match_modes
from roboprobe.analysis.modes import ModeSummarizer
from roboprobe.analysis.ports import (
    AnalysisArtifactStore,
    AnalysisRunRow,
    AnalysisUnitOfWork,
)
from roboprobe.analysis.rules import RuleExtractor
from roboprobe.analysis.settings import (
    ClustererSettings,
    ImportanceSettings,
    LabelLexicon,
    RuleExtractorSettings,
)
from roboprobe.analysis.types import (
    AnalysisRun,
    FailureModeSummary,
    ImportanceReport,
    ParamRange,
    StoredMode,
)
from roboprobe.core.clock import Clock
from roboprobe.core.errors import ModelFitError, NotFoundError, ValidationError
from roboprobe.core.metrics_registry import Metrics
from roboprobe.core.settings.analysis import AnalysisSettings, RiskSettings
from roboprobe.core.settings.selection import GpDefaults
from roboprobe.core.types import FailureClass, JsonValue, ParamValue, Phase, Verdict
from roboprobe.risk import RiskMapper, VolumeEstimator, robustness_score, save_slices
from roboprobe.scenario._documents import validate_document
from roboprobe.scenario.space import ScenarioSpace

__all__ = [
    "analyze_campaign",
    "default_analyzers",
    "load_analyzers",
]

_LOGGER = logging.getLogger(__name__)

_CORE_STEPS: Final = frozenset({"features", "clustering", "modes"})
_SCHEMA_VERSION: Final = 1
_MIN_GP_DIM: Final = 2
_KIND_DB: dict[AnalysisKind, str] = {
    AnalysisKind.FULL: "final",
    AnalysisKind.INCREMENTAL: "incremental",
}
_TOPIC_ANALYSIS_FINISHED: Final = "analysis.finished"
_SKIP_PHASES = frozenset({"confirm"})


def analyze_campaign(  # noqa: PLR0913
    campaign_id: UUID,
    uow: AnalysisUnitOfWork,
    artifact_store: AnalysisArtifactStore,
    *,
    kind: AnalysisKind = AnalysisKind.FULL,
    settings: AnalysisSettings,
    risk: RiskSettings | None = None,
    clock: Clock,
    metrics: Metrics | None = None,
    load_space: Callable[[str, str], ScenarioSpace] | None = None,
    analyzers: Sequence[Analyzer] | None = None,
) -> AnalysisReport:
    """Run the analysis chain for ``campaign_id`` and persist results.

    Implements: T-075a, FR-ANA-006
    """
    if load_space is None:
        msg = "load_space is required"
        raise ValidationError(msg)
    campaign = uow.campaigns.get(campaign_id)
    if campaign is None:
        msg = "campaign not found"
        raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
    analysis_id = uuid4()
    started = clock.monotonic()
    risk_settings = risk or RiskSettings()
    space = load_space(campaign.space_id, campaign.space_version)
    runs, gp_x, gp_y = _load_runs(uow, campaign_id)
    chain = list(analyzers) if analyzers is not None else _chain_for_kind(kind)
    ctx = AnalysisContext(
        campaign_id=campaign_id,
        kind=kind,
        settings=settings,
        risk=risk_settings,
        clock=clock,
        uow=uow,
        artifact_store=artifact_store,
        space=space,
        campaign_seed=int(campaign.seed),
        backend=str(campaign.backend),
        runs=runs,
        analysis_id=analysis_id,
        gp_x=gp_x,
        gp_y=gp_y,
    )
    core_error: Exception | None = None
    for step in chain:
        core = step.name in _CORE_STEPS
        try:
            _run_step(ctx, step, metrics=metrics, core=core)
        except Exception as exc:
            if core:
                core_error = exc
                ctx.warnings.append(f"{step.name}: {exc}")
                break
            ctx.warnings.append(f"{step.name}: {exc}")
            continue
    finished = clock.monotonic()
    duration = finished - started
    n_fail = sum(1 for run in runs if run.verdict is Verdict.FAIL)
    status = _status(ctx, core_error)
    mode_codes = [m.code for m in ctx.modes] if core_error is None else []
    report = AnalysisReport(
        analysis_id=analysis_id,
        campaign_id=campaign_id,
        kind=kind,
        status=status,
        analysis_schema_version=_SCHEMA_VERSION,
        n_runs=len(runs),
        n_fail=n_fail,
        mode_codes=mode_codes,
        warnings=list(ctx.warnings),
        summary=_summary(ctx),
        duration_s=duration,
    )
    try:
        report = _write_artefacts(
            ctx,
            report,
            campaign_id,
            artifact_store,
            kind=kind,
            include_slices=kind is AnalysisKind.FULL,
        )
    except Exception as exc:
        _LOGGER.warning("analysis.artefact_write_failed", exc_info=exc)
        ctx.warnings.append(f"artefacts: {exc}")
        report = replace(
            report,
            warnings=list(ctx.warnings),
            status=_coalesce_partial(report.status),
        )
    _persist(ctx, report, clock, core_error)
    return report


def default_analyzers() -> list[Analyzer]:
    """Built-in analysis steps for :meth:`analyze_campaign` (group ``roboprobe.analyzers``)."""
    return [
        FeaturesAnalyzer(),
        ClusteringAnalyzer(),
        ModesAnalyzer(),
        RiskVolumesAnalyzer(),
        ImportanceAnalyzer(),
        RulesAnalyzer(),
    ]


def load_analyzers() -> list[Analyzer]:
    """Load analyzer plugins from the ``roboprobe.analyzers`` entry-point group."""
    eps = importlib.metadata.entry_points().select(group="roboprobe.analyzers")
    loaded: list[Analyzer] = []
    for ep in eps:
        obj = ep.load()
        loaded.append(obj() if isinstance(obj, type) else cast(Analyzer, obj))
    return loaded


class FeaturesAnalyzer:
    """Build the failure feature matrix."""

    name: str = "features"

    def run(self, ctx: AnalysisContext) -> None:
        """Populate :attr:`AnalysisContext.features`."""
        if ctx.space is None:
            msg = "scenario space is required"
            raise ValidationError(msg)
        builder = FailureFeatureBuilder(ctx.settings.feature_weights)
        ctx.features = builder.build(ctx.runs, ctx.space)


class ClusteringAnalyzer:
    """Cluster failing runs."""

    name: str = "clustering"

    def run(self, ctx: AnalysisContext) -> None:
        if ctx.features is None:
            msg = "features step must run first"
            raise ValidationError(msg)
        hdb = ctx.settings.hdbscan
        clusterer = FailureClusterer(
            ClustererSettings(
                min_cluster_fraction=hdb.min_cluster_fraction,
                min_cluster_size_floor=hdb.min_cluster_size_floor,
            )
        )
        ctx.clustering = clusterer.fit(ctx.features)


class ModesAnalyzer:
    """Summarise clusters and match stable mode codes."""

    name: str = "modes"

    def run(self, ctx: AnalysisContext) -> None:
        if ctx.clustering is None or ctx.space is None:
            msg = "clustering and space are required"
            raise ValidationError(msg)
        summarizer = ModeSummarizer(
            characteristic_coverage=ctx.settings.characteristic_coverage,
            lexicon=LabelLexicon(),
            seed=ctx.campaign_seed,
        )
        raw = summarizer.summarize(ctx.clustering, ctx.runs, ctx.space)
        previous = _stored_modes(ctx.uow, ctx.campaign_id)
        match = match_modes(previous, raw, ctx.settings.mode_match_jaccard)
        modes: list[FailureModeSummary] = []
        mode_ids: dict[str, UUID] = {}
        for i, summary in enumerate(raw):
            code = match.new_codes[i]
            label = match.preserved_labels.get(i, summary.label)
            modes.append(summary.model_copy(update={"code": code, "label": label}))
            mode_ids[code] = match.assignments.get(i, uuid4())
        ctx.modes = modes
        ctx.mode_ids = mode_ids


class ImportanceAnalyzer:
    """Optional SHAP importance (soft-fail)."""

    name: str = "importance"

    def run(self, ctx: AnalysisContext) -> None:
        if ctx.space is None:
            msg = "scenario space is required"
            raise ValidationError(msg)
        matrix, names, y_fail, run_ids = _design_matrix(ctx)
        settings = ImportanceSettings.from_analysis(ctx.settings)
        explainer = ImportanceExplainer(settings, seed=ctx.campaign_seed)
        ctx.importance = explainer.explain(
            matrix,
            y_fail,
            names,
            lengthscales=ctx.gp_lengthscales,
            modes=ctx.modes,
            run_ids=run_ids,
        )


class RulesAnalyzer:
    """Optional decision-tree rules (soft-fail)."""

    name: str = "rules"

    def run(self, ctx: AnalysisContext) -> None:
        if ctx.space is None:
            msg = "scenario space is required"
            raise ValidationError(msg)
        matrix, names, y_fail, run_ids = _design_matrix(ctx)
        settings = RuleExtractorSettings(
            max_depth=ctx.settings.rules.max_depth,
            min_precision=ctx.settings.rules.min_precision,
        )
        extractor = RuleExtractor(settings, seed=ctx.campaign_seed)
        ctx.rules = extractor.extract(
            matrix, y_fail, names, ctx.space, modes=ctx.modes, run_ids=run_ids
        )


class RiskVolumesAnalyzer:
    """Fit a GP surrogate when available and estimate risk volumes (optional slices)."""

    name: str = "risk_volumes"

    def run(self, ctx: AnalysisContext) -> None:
        if ctx.space is None:
            msg = "scenario space is required"
            raise ValidationError(msg)
        gp_mod = importlib.import_module("roboprobe.selection.surrogate")
        robustness_gp = gp_mod.RobustnessGP
        x = np.asarray(ctx.gp_x, dtype=np.float64)
        y = np.asarray(ctx.gp_y, dtype=np.float64)
        if x.size == 0 or y.size == 0 or ctx.space.dim < _MIN_GP_DIM:
            ctx.warnings.append("risk_volumes: insufficient GP training data")
            return
        gp = robustness_gp(
            ctx.space.dim,
            seed=ctx.campaign_seed,
            gp=GpDefaults(),
            metrics=None,
            clock=ctx.clock,
        )
        try:
            gp.fit(x, y)
        except ModelFitError as exc:
            ctx.warnings.append(f"risk_volumes: GP fit failed ({exc})")
            return
        scales = getattr(gp, "lengthscales", ())
        if len(scales) == ctx.space.dim:
            ctx.gp_lengthscales = {
                parameter.id: float(scale)
                for parameter, scale in zip(ctx.space.params, scales, strict=True)
            }
        try:
            mapper = RiskMapper(gp, ctx.space, ctx.risk.thresholds)
        except ValidationError as exc:
            ctx.warnings.append(f"risk_volumes: mapper unavailable ({exc})")
            return
        estimator = VolumeEstimator()
        vol = estimator.estimate(mapper, n=ctx.risk.volume_samples, seed=ctx.campaign_seed)
        ctx.volumes = {
            "safe": vol.safe,
            "uncertain": vol.uncertain,
            "failure": vol.failure,
            "safe_ci": vol.safe_ci,
            "uncertain_ci": vol.uncertain_ci,
            "failure_ci": vol.failure_ci,
            "n": vol.n,
            "seed": vol.seed,
            "robustness_score": robustness_score(vol),
        }
        if ctx.kind is AnalysisKind.FULL:
            anchor = ctx.space.nominal_values()
            ctx.slices = mapper.all_pair_slices(anchor, resolution=ctx.risk.slice_resolution)


def _chain_for_kind(kind: AnalysisKind) -> list[Analyzer]:
    built = default_analyzers()
    if kind is AnalysisKind.INCREMENTAL:
        keep = {"features", "clustering", "modes", "risk_volumes"}
        return [step for step in built if step.name in keep]
    return built


def _run_step(
    ctx: AnalysisContext,
    analyzer: Analyzer,
    *,
    metrics: Metrics | None,
    core: bool,
) -> None:
    started = ctx.clock.monotonic()
    try:
        analyzer.run(ctx)
    except Exception:
        if not core:
            ctx.optional_failed = True
        raise
    finally:
        elapsed = ctx.clock.monotonic() - started
        ctx.step_seconds[analyzer.name] = elapsed
        if metrics is not None and getattr(metrics, "analysis_step_seconds", None) is not None:
            metrics.analysis_step_seconds.labels(step=analyzer.name).observe(elapsed)


def _load_runs(
    uow: AnalysisUnitOfWork,
    campaign_id: UUID,
) -> tuple[list[AnalysisRun], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    out: list[AnalysisRun] = []
    xs: list[list[float]] = []
    ys: list[float] = []
    cursor: str | None = None
    while True:
        page = uow.runs.list_for_campaign(campaign_id, cursor=cursor)
        for row in page.items:
            analysis_run = _to_analysis_run(row)
            out.append(analysis_run)
            if row.robustness is not None and np.isfinite(row.robustness):
                xs.append([float(v) for v in row.x_unit])
                ys.append(float(row.robustness))
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    gp_x = np.asarray(xs, dtype=np.float64) if xs else np.empty((0, 0), dtype=np.float64)
    gp_y = np.asarray(ys, dtype=np.float64)
    return out, gp_x, gp_y


def _to_analysis_run(row: AnalysisRunRow) -> AnalysisRun:
    verdict = row.verdict if isinstance(row.verdict, Verdict) else Verdict(str(row.verdict))
    phase: Phase = cast(Phase, row.phase if row.phase in _PHASE_VALUES else "falsify")
    primary = None
    if row.primary_failure:
        try:
            primary = FailureClass(str(row.primary_failure))
        except ValueError:
            primary = None
    metrics_f: dict[str, float] = {}
    for key, value in (row.metrics or {}).items():
        try:
            metrics_f[str(key)] = float(cast(float | int | str, value))
        except (TypeError, ValueError):
            continue
    values = {str(k): cast(ParamValue, v) for k, v in dict(row.scenario_values or {}).items()}
    return AnalysisRun(
        id=row.id,
        ordinal=getattr(row, "ordinal", None),
        verdict=verdict,
        phase=phase,
        primary_failure=primary,
        values=values,
        metrics=metrics_f,
    )


_PHASE_VALUES = frozenset(
    {
        "warmup",
        "falsify",
        "mode_search",
        "boundary",
        "refine",
        "explore",
        "baseline",
        "manual",
        "confirm",
        "replay",
    }
)


def _stored_modes(uow: AnalysisUnitOfWork, campaign_id: UUID) -> list[StoredMode]:
    records = uow.modes.list_for_campaign(campaign_id)
    members = _member_map(uow, campaign_id)
    return [
        StoredMode(
            id=rec.id,
            code=rec.code,
            member_run_ids=members.get(rec.id, frozenset()),
            label=rec.label,
            label_is_user=rec.label_is_user,
            status=rec.status,
        )
        for rec in records
    ]


def _member_map(uow: AnalysisUnitOfWork, campaign_id: UUID) -> dict[UUID, frozenset[UUID]]:
    fn = getattr(uow.modes, "list_members_for_campaign", None)
    if not callable(fn):
        return {}
    acc: dict[UUID, set[UUID]] = {}
    for mem in fn(campaign_id):
        acc.setdefault(mem.mode_id, set()).add(mem.run_id)
    return {mid: frozenset(rids) for mid, rids in acc.items()}


def _design_matrix(
    ctx: AnalysisContext,
) -> tuple[npt.NDArray[np.float64], list[str], npt.NDArray[np.bool_], tuple[UUID, ...]]:
    if ctx.space is None:
        msg = "scenario space is required"
        raise ValidationError(msg)
    active = [r for r in ctx.runs if r.phase not in _SKIP_PHASES]
    run_ids = tuple(r.id for r in active)
    if not active:
        dim = ctx.space.dim
        return (
            np.empty((0, dim), dtype=np.float64),
            [p.id for p in ctx.space.params],
            np.empty(0, dtype=bool),
            run_ids,
        )
    matrix = np.vstack([ctx.space.to_unit(r.values) for r in active])
    y_fail = np.array([r.verdict is Verdict.FAIL for r in active], dtype=bool)
    names = [p.id for p in ctx.space.params]
    return matrix, names, y_fail, run_ids


def _status(ctx: AnalysisContext, core_error: Exception | None) -> str:
    if core_error is not None:
        return "ERROR"
    if ctx.optional_failed:
        return "PARTIAL"
    return "OK"


def _coalesce_partial(status: str) -> str:
    return "PARTIAL" if status == "OK" else status


def _summary(ctx: AnalysisContext) -> dict[str, Any]:
    summary: dict[str, Any] = {"step_seconds": dict(ctx.step_seconds)}
    if ctx.clustering is not None:
        summary["clustering"] = {
            "method": ctx.clustering.method,
            "provisional": ctx.clustering.provisional,
            "min_cluster_size": ctx.clustering.min_cluster_size,
        }
    summary["n_modes"] = len(ctx.modes)
    if ctx.importance is not None:
        summary["importance"] = ctx.importance.model_dump(mode="json")
        summary["interactions"] = {
            "names": list(ctx.importance.names),
            "values": [list(row) for row in ctx.importance.interactions],
        }
    summary["rules"] = [rule.model_dump(mode="json") for rule in ctx.rules]
    if ctx.volumes is not None:
        summary["volumes"] = dict(ctx.volumes)
    summary["n_rules"] = len(ctx.rules)
    return summary


def _write_artefacts(  # noqa: PLR0913
    ctx: AnalysisContext,
    report: AnalysisReport,
    campaign_id: UUID,
    artifact_store: AnalysisArtifactStore,
    *,
    kind: AnalysisKind,
    include_slices: bool,
) -> AnalysisReport:
    del kind
    sha256: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="roboprobe-analysis-") as tmp:
        root = Path(tmp)
        report_path = root / "report.json"
        document = _report_document(report)
        report_path.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
        validate_document(document, schema="analysis_report", source=str(report_path))
        sha256["report.json"] = _put_artifact(
            artifact_store, report_path, "analysis", campaign_id=campaign_id
        )
        if ctx.modes and report.status != "ERROR":
            modes_path = root / "modes.parquet"
            _write_modes_parquet(modes_path, ctx.modes)
            sha256["modes.parquet"] = _put_artifact(
                artifact_store, modes_path, "analysis", campaign_id=campaign_id
            )
        if ctx.importance is not None:
            shap_path = root / "shap_values.npz"
            _write_shap(shap_path, ctx.importance)
            sha256["shap_values.npz"] = _put_artifact(
                artifact_store, shap_path, "analysis", campaign_id=campaign_id
            )
        if include_slices and ctx.slices:
            slices_path = root / "risk_slices.npz"
            save_slices(slices_path, ctx.slices)
            sha256["risk_slices.npz"] = _put_artifact(
                artifact_store, slices_path, "risk_slices", campaign_id=campaign_id
            )
    return replace(report, artefact_sha256=sha256)


def _report_document(report: AnalysisReport) -> dict[str, object]:
    return {
        "analysis_schema_version": report.analysis_schema_version,
        "analysis_id": str(report.analysis_id),
        "campaign_id": str(report.campaign_id),
        "kind": report.kind.value,
        "status": report.status,
        "n_runs": report.n_runs,
        "n_fail": report.n_fail,
        "mode_codes": list(report.mode_codes),
        "warnings": list(report.warnings),
        "summary": report.summary,
        "duration_s": report.duration_s,
        **({"artefact_sha256": dict(report.artefact_sha256)} if report.artefact_sha256 else {}),
    }


def _put_artifact(
    store: AnalysisArtifactStore,
    path: Path,
    kind: str,
    *,
    campaign_id: UUID,
) -> str:
    ref = store.put(path, kind=kind, campaign_id=campaign_id)
    return str(ref.sha256)


def _write_modes_parquet(path: Path, modes: Sequence[FailureModeSummary]) -> None:
    rows: list[dict[str, object]] = []
    for mode in modes:
        rows.append(
            {
                "code": mode.code,
                "label": mode.label,
                "size": mode.size,
                "primary_class": mode.primary_class.value,
                "characteristic": sorted(mode.characteristic),
                "provisional": mode.provisional,
            }
        )
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path)


def _write_shap(path: Path, importance: ImportanceReport) -> None:
    np.savez_compressed(
        path,
        names=np.asarray(importance.names, dtype=object),
        mean_abs_shap=np.asarray(importance.mean_abs_shap, dtype=np.float64),
        interactions=np.asarray(importance.interactions, dtype=np.float64),
    )


def _persist(
    ctx: AnalysisContext,
    report: AnalysisReport,
    clock: Clock,
    core_error: Exception | None,
) -> None:
    records = importlib.import_module("roboprobe.store.records")
    analysis_record = records.AnalysisRecord
    failure_mode_record = records.FailureModeRecord
    failure_member_record = records.FailureModeMemberRecord
    db_status = "ERROR" if core_error is not None else "DONE"
    report_sha = report.artefact_sha256.get("report.json")
    ctx.uow.analyses.add(
        analysis_record(
            id=report.analysis_id,
            campaign_id=report.campaign_id,
            kind=_KIND_DB[report.kind],
            status=db_status,
            n_runs=report.n_runs,
            summary=cast(dict[str, JsonValue], report.summary),
            report_sha256=report_sha,
            analysis_schema_version=report.analysis_schema_version,
            finished_at=clock.now(),
        )
    )
    if core_error is not None:
        ctx.uow.events.append(
            _TOPIC_ANALYSIS_FINISHED,
            {
                "campaign_id": str(report.campaign_id),
                "analysis_id": str(report.analysis_id),
                "kind": _KIND_DB[report.kind],
            },
            campaign_id=report.campaign_id,
        )
        return
    modes, members = _mode_records(ctx, failure_mode_record, failure_member_record)
    ctx.uow.modes.upsert_modes(report.campaign_id, modes, members)
    ctx.uow.events.append(
        _TOPIC_ANALYSIS_FINISHED,
        {
            "campaign_id": str(report.campaign_id),
            "analysis_id": str(report.analysis_id),
            "kind": _KIND_DB[report.kind],
        },
        campaign_id=report.campaign_id,
    )


def _mode_records(
    ctx: AnalysisContext,
    failure_mode_record: Any,  # noqa: ANN401
    member_record: Any,  # noqa: ANN401
) -> tuple[list[Any], list[Any]]:
    rules_by_code: dict[str, list[dict[str, object]]] = {}
    for rule in ctx.rules:
        code = rule.mode_code or ""
        rules_by_code.setdefault(code, []).append(json.loads(rule.model_dump_json()))
    modes: list[Any] = []
    members: list[Any] = []
    probabilities = (
        dict(zip(ctx.clustering.run_ids, ctx.clustering.probabilities, strict=True))
        if ctx.clustering is not None
        else {}
    )
    ordinals = {run.id: run.ordinal for run in ctx.runs if run.ordinal is not None}
    for summary in ctx.modes:
        mode_id = ctx.mode_ids[summary.code]
        class_mix = {k.value: float(v) for k, v in summary.class_mix.items()}
        param_ranges = {pid: _param_range_json(rng) for pid, rng in summary.ranges.items()}
        modes.append(
            failure_mode_record(
                id=mode_id,
                campaign_id=ctx.campaign_id,
                code=summary.code,
                label=summary.label,
                label_is_user=False,
                primary_class=summary.primary_class.value,
                class_mix=class_mix,
                size=summary.size,
                param_ranges=param_ranges,
                characteristic=tuple(sorted(summary.characteristic)),
                medoid_run_id=summary.medoid_run_id,
                minimal_run_id=summary.minimal_run_id,
                first_seen_run=min(
                    (run_id for run_id in summary.member_run_ids if run_id in ordinals),
                    key=ordinals.__getitem__,
                    default=None,
                ),
                rules=rules_by_code.get(summary.code, []),
                analysis_id=ctx.analysis_id,
            )
        )
        for run_id in summary.member_run_ids:
            membership = float(probabilities.get(run_id, 1.0))
            members.append(member_record(mode_id=mode_id, run_id=run_id, membership=membership))
    return modes, members


def _param_range_json(rng: ParamRange) -> dict[str, object]:
    return {
        "unit": rng.unit,
        "q05": rng.q05,
        "q95": rng.q95,
        "space_coverage": rng.space_coverage,
    }
