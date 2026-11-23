"""Experiment runner: plan → concurrent campaigns → comparison results (docs/14 §8).

Implements: T-102b, FR-EXP-001, FR-EXP-002, PR-10
"""

# ruff: noqa: D102, D107

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from numpy.typing import ArrayLike

from roboprobe.core.clock import Clock
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.core.seeding import ANALYSIS, derive_seed
from roboprobe.core.settings.experiments import ExperimentSettings
from roboprobe.core.types import CampaignStatus, JsonValue, Verdict
from roboprobe.experiments.planner import CampaignSpec, ComparabilityKey, ExperimentDesign, plan
from roboprobe.metrics.campaign_metrics import (
    CampaignRun,
    comparison_runs,
    failure_discovery_rate,
    first_failure,
    is_comparison_run,
)
from roboprobe.metrics.discovery_metrics import discovery_auc
from roboprobe.metrics.statistics import compare
from roboprobe.selection.benchmarks import (
    BRANIN_MODES,
    MODE_CANONICAL,
    label_branin_mode,
    label_mode,
)

__all__ = [
    "EXPERIMENT_TERMINAL",
    "N_MULTIMODE_TARGETS",
    "AnalyticGroundTruth",
    "CampaignDriver",
    "ExperimentRunner",
    "ExperimentWriter",
    "analytic_ground_truth",
    "analytic_mode_labels",
    "build_comparison",
    "export_raw_parquet",
    "is_analytic_multimode",
]

EXPERIMENT_TERMINAL = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
_CAMPAIGN_DONE = frozenset(
    {CampaignStatus.COMPLETED, CampaignStatus.FAILED, CampaignStatus.CANCELLED}
)
_MET_01 = "MET-01"
_MET_02 = "MET-02"
_MET_03 = "MET-03"
_MET_09 = "MET-09"
_DEFAULT_METRICS = (_MET_01, _MET_03)
_DISCOVERY_METRICS = (_MET_02, _MET_09)
VARIANT_TAG_PREFIX = "variant:"
N_MULTIMODE_TARGETS = len(MODE_CANONICAL)


class ExperimentWriter(Protocol):
    """Persistence facade (store stays out of this package; docs/16 §2)."""

    def add_experiment(self, *, name: str, design: dict[str, JsonValue], status: str) -> UUID: ...

    def add_campaign(self, spec: CampaignSpec, experiment_id: UUID) -> UUID: ...

    def get_experiment(self, experiment_id: UUID) -> object | None: ...

    def set_experiment_status(
        self, experiment_id: UUID, status: str, *, finished: bool = False
    ) -> None: ...

    def set_experiment_results(
        self, experiment_id: UUID, results: dict[str, JsonValue]
    ) -> None: ...

    def list_campaigns(self, experiment_id: UUID) -> Sequence[object]: ...

    def campaign_runs(self, campaign_id: UUID) -> Sequence[CampaignRun]: ...


class CampaignDriver(Protocol):
    """Drive one campaign to a terminal status (inline loop or enqueue)."""

    def __call__(self, campaign_id: UUID) -> CampaignStatus: ...


@dataclass(frozen=True, slots=True)
class _CampaignRow:
    id: UUID
    strategy_label: str
    strategy_id: str
    budget: int
    status: CampaignStatus
    experiment_rep: int | None


@dataclass(frozen=True, slots=True)
class AnalyticGroundTruth:
    """Exact failure-mode classifier and denominator for a known benchmark."""

    label: Callable[[ArrayLike], str | None]
    n_modes: int


_MULTIMODE = AnalyticGroundTruth(label_mode, N_MULTIMODE_TARGETS)
_ANALYTIC_SPACES = {
    "branin_2d": AnalyticGroundTruth(label_branin_mode, len(BRANIN_MODES)),
    "multi_mode_6d": _MULTIMODE,
}


def analytic_ground_truth(design: Mapping[str, JsonValue]) -> AnalyticGroundTruth | None:
    """Select ground truth only for supported, unpinned benchmark designs."""
    space = design.get("space")
    if design.get("backend") != "benchmark" or not isinstance(space, dict) or design.get("pins"):
        return None
    space_id = space.get("id")
    return _ANALYTIC_SPACES.get(space_id) if isinstance(space_id, str) else None


def is_analytic_multimode(design: Mapping[str, JsonValue]) -> bool:
    """Return whether the design uses the unpinned six-dimensional benchmark."""
    return analytic_ground_truth(design) is _MULTIMODE


def analytic_mode_labels(
    runs: Sequence[CampaignRun], ground_truth: AnalyticGroundTruth = _MULTIMODE
) -> list[str | None]:
    """Label observed failures with the benchmark's noise-free mode classifier."""
    return [
        ground_truth.label(run.x_unit) if run.verdict is Verdict.FAIL else None
        for run in comparison_runs(runs)
    ]


def _available_metrics(
    metrics: Sequence[str], ground_truth: AnalyticGroundTruth | None
) -> tuple[str, ...]:
    requested = tuple(metrics) or _DEFAULT_METRICS
    supported = _DEFAULT_METRICS + (_DISCOVERY_METRICS if ground_truth is not None else ())
    for metric in requested:
        if metric not in supported:
            msg = f"unsupported experiment metric {metric}"
            raise ValidationError(msg, context={"metric": metric})
    return requested


def _metric_value(
    metric: str, runs: Sequence[CampaignRun], budget: int, ground_truth: AnalyticGroundTruth | None
) -> float:
    if metric == _MET_01:
        fdr, _fdr_h = failure_discovery_rate(runs)
        return float(fdr)
    if metric == _MET_03:
        first = first_failure(runs, budget=budget)
        return float(first.n1 + 1 if first.censored else first.n1)
    if ground_truth is None:
        msg = "discovery metrics require analytical ground truth"
        raise ValidationError(msg, context={"metric": metric})
    labels = analytic_mode_labels(runs, ground_truth)
    if metric == _MET_02:
        return float(len({label for label in labels if label is not None}))
    return discovery_auc(labels, ground_truth.n_modes, budget=budget)


def build_comparison(  # noqa: PLR0913 - comparison inputs are independent axes
    experiment_id: UUID,
    campaigns: Sequence[_CampaignRow],
    runs_by_campaign: Mapping[UUID, Sequence[CampaignRun]],
    *,
    metrics: Sequence[str],
    settings: ExperimentSettings,
    rng: np.random.Generator,
    analytic_multimode: bool = False,
    ground_truth: AnalyticGroundTruth | None = None,
) -> dict[str, JsonValue]:
    """Assemble docs/12 §3.5 ``ExperimentComparison`` from finished campaigns."""
    if ground_truth is None and analytic_multimode:
        ground_truth = _MULTIMODE
    metric_ids = _available_metrics(metrics, ground_truth)
    by_label: dict[str, list[_CampaignRow]] = {}
    for camp in campaigns:
        by_label.setdefault(camp.strategy_label, []).append(camp)

    strategies_out: dict[str, dict[str, JsonValue]] = {}
    tests_out: list[JsonValue] = []
    metrics_present: list[str] = []

    for metric in metric_ids:
        samples: dict[str, list[float]] = {}
        for label, rows in by_label.items():
            samples[label] = [
                _metric_value(metric, runs_by_campaign.get(row.id, ()), row.budget, ground_truth)
                for row in sorted(rows, key=lambda r: r.experiment_rep or 0)
            ]
        reference = next(iter(samples))
        for label in samples:
            if "PROBE" in label:
                reference = label
                break
        higher = metric != _MET_03
        payload = compare(
            samples,
            metric=metric,
            reference=reference,
            n_resamples=settings.bootstrap_resamples,
            alpha=settings.alpha,
            rng=rng,
            higher_is_better=higher,
        )
        metrics_present.append(metric)
        strat_map = cast("dict[str, Any]", payload["strategies"])
        for label, metric_block in strat_map.items():
            block = cast("dict[str, Any]", metric_block)
            strategies_out.setdefault(str(label), {}).update({str(k): v for k, v in block.items()})
        tests_out.extend(cast("list[JsonValue]", payload["tests"]))

    return cast(
        "dict[str, JsonValue]",
        {
            "experiment_id": str(experiment_id),
            "metrics": list(metrics_present),
            "strategies": strategies_out,
            "tests": tests_out,
        },
    )


def export_raw_parquet(
    path: Path,
    campaigns: Sequence[_CampaignRow],
    runs_by_campaign: Mapping[UUID, Sequence[CampaignRun]],
) -> None:
    """Write per-run rows for independent re-analysis (docs/19 §7)."""
    strategy: list[str] = []
    rep: list[int] = []
    ordinal: list[int] = []
    verdict: list[str] = []
    wall: list[float] = []
    coordinates: list[tuple[float, ...]] = []
    comparison: list[bool] = []
    for camp in campaigns:
        for index, run in enumerate(runs_by_campaign.get(camp.id, ())):
            strategy.append(camp.strategy_label)
            rep.append(int(camp.experiment_rep or 0))
            ordinal.append(index)
            verdict.append(run.verdict.value)
            wall.append(float(run.wall_time_s))
            coordinates.append(run.x_unit)
            comparison.append(is_comparison_run(run))
    table = pa.table(
        {
            "strategy": strategy,
            "experiment_rep": rep,
            "ordinal": ordinal,
            "verdict": verdict,
            "wall_time_s": wall,
            "x_unit": pa.array(coordinates, type=pa.list_(pa.float64())),
            "is_comparison_run": pa.array(comparison, type=pa.bool_()),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def _variant_label(raw: object) -> str:
    tags = getattr(raw, "tags", ()) or ()
    for tag in tags:
        text = str(tag)
        if text.startswith(VARIANT_TAG_PREFIX):
            return text[len(VARIANT_TAG_PREFIX) :]
    return str(getattr(raw, "strategy_id", ""))


class _CampaignLike(Protocol):
    id: UUID
    strategy_id: str
    budget: int
    status: CampaignStatus | str
    experiment_rep: int | None
    tags: Sequence[str]


def _as_campaign_row(raw: object) -> _CampaignRow:
    camp = cast("_CampaignLike", raw)
    if isinstance(camp.status, CampaignStatus):
        status = camp.status
    else:
        status = CampaignStatus(str(camp.status))
    return _CampaignRow(
        id=camp.id,
        strategy_label=_variant_label(raw),
        strategy_id=str(camp.strategy_id),
        budget=int(camp.budget),
        status=status,
        experiment_rep=camp.experiment_rep,
    )


class ExperimentRunner:
    """Create/run experiment campaigns with a concurrency limit; resume unfinished cells."""

    def __init__(
        self,
        writer: ExperimentWriter,
        settings: ExperimentSettings,
        clock: Clock,
        drive: CampaignDriver,
        *,
        new_uuid: Callable[[], UUID],
    ) -> None:
        self._writer = writer
        self._settings = settings
        self._clock = clock
        self._drive = drive
        self._new_uuid = new_uuid

    def start(
        self,
        design: ExperimentDesign,
        key: ComparabilityKey,
        *,
        experiment_id: UUID | None = None,
        raw_parquet: Path | None = None,
    ) -> tuple[UUID, dict[str, JsonValue]]:
        """Plan, create rows (unless resuming), drive unfinished campaigns, store comparison.

        Args:
            design: Validated experiment design.
            key: Shared comparability fingerprint.
            experiment_id: Resume this experiment; skip terminal campaigns.
            raw_parquet: Optional path for the raw Parquet export.

        Returns:
            ``(experiment_id, ExperimentComparison)``.
        """
        design_doc = design.model_dump(mode="json")
        ground_truth = analytic_ground_truth(design_doc)
        _available_metrics(design.metrics, ground_truth)
        specs = plan(design, default_seeds=self._settings.default_seeds, key=key)
        if experiment_id is None:
            experiment_id = self._create(design, specs)
        elif self._writer.get_experiment(experiment_id) is None:
            msg = "experiment not found"
            raise NotFoundError(msg, context={"experiment_id": str(experiment_id)})

        self._writer.set_experiment_status(experiment_id, "RUNNING")
        rows = [_as_campaign_row(c) for c in self._writer.list_campaigns(experiment_id)]
        pending = [row for row in rows if row.status not in _CAMPAIGN_DONE]
        self._drive_many(pending)

        rows = [_as_campaign_row(c) for c in self._writer.list_campaigns(experiment_id)]
        runs_by = {row.id: tuple(self._writer.campaign_runs(row.id)) for row in rows}
        if any(row.status is CampaignStatus.FAILED for row in rows):
            self._writer.set_experiment_status(experiment_id, "FAILED", finished=True)
            msg = "one or more experiment campaigns failed"
            raise ValidationError(msg, context={"experiment_id": str(experiment_id)})

        rng = np.random.Generator(
            np.random.PCG64(derive_seed(design.seeds.root, ANALYSIS, "compare"))
        )
        comparison = build_comparison(
            experiment_id,
            rows,
            runs_by,
            metrics=design.metrics,
            settings=self._settings,
            rng=rng,
            ground_truth=ground_truth,
        )
        self._writer.set_experiment_results(experiment_id, comparison)
        self._writer.set_experiment_status(experiment_id, "COMPLETED", finished=True)
        if raw_parquet is not None:
            export_raw_parquet(raw_parquet, rows, runs_by)
        _ = self._clock.now()
        return experiment_id, comparison

    def report(self, experiment_id: UUID) -> dict[str, JsonValue]:
        """Return stored comparison JSON (docs/12 §3.5)."""
        exp = self._writer.get_experiment(experiment_id)
        if exp is None:
            msg = "experiment not found"
            raise NotFoundError(msg, context={"experiment_id": str(experiment_id)})
        results = getattr(exp, "results", None)
        if not isinstance(results, dict):
            msg = "experiment has no results yet"
            raise ValidationError(msg, context={"experiment_id": str(experiment_id)})
        return dict(results)

    def _create(self, design: ExperimentDesign, specs: list[CampaignSpec]) -> UUID:
        design_doc: dict[str, JsonValue] = {
            "id": design.id,
            "backend": design.backend,
            "space": {"id": design.space.id, "version": design.space.version},
            "budget": design.budget,
            "pins": dict(design.pins),
            "seeds": {"root": design.seeds.root, "count": design.seeds.count},
            "strategies": [
                {"id": s.id, "label": s.label, "params": dict(s.params)} for s in design.strategies
            ],
            "metrics": list(design.metrics),
        }
        eid = self._writer.add_experiment(
            name=design.name or design.id, design=design_doc, status="CREATED"
        )
        for spec in specs:
            tag = f"{VARIANT_TAG_PREFIX}{spec.strategy_label}"
            stamped = CampaignSpec(
                experiment_id=spec.experiment_id,
                experiment_rep=spec.experiment_rep,
                name=spec.name,
                strategy_id=spec.strategy_id,
                strategy_label=spec.strategy_label,
                strategy_params=dict(spec.strategy_params),
                seed=spec.seed,
                budget=spec.budget,
                repeats=spec.repeats,
                batch_size=spec.batch_size,
                backend=spec.backend,
                space_id=spec.space_id,
                space_version=spec.space_version,
                sut_profile_id=spec.sut_profile_id,
                pins=spec.pins,
                oracle_overrides=spec.oracle_overrides,
                stop_rules=spec.stop_rules,
                tags=(*spec.tags, tag),
                metrics=spec.metrics,
                comparability=spec.comparability,
            )
            self._writer.add_campaign(stamped, eid)
        return eid

    def _drive_many(self, pending: Sequence[_CampaignRow]) -> None:
        if not pending:
            return
        workers = max(1, self._settings.max_concurrent_campaigns)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._drive, row.id): row.id for row in pending}
            for fut in as_completed(futures):
                fut.result()
