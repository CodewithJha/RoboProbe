"""Comparison inputs shared by the experiment API and offline report (T-084a)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import isfinite
from typing import Protocol, cast
from uuid import UUID

import numpy as np

from roboprobe.core.seeding import ANALYSIS, derive_seed
from roboprobe.core.settings.experiments import ExperimentSettings
from roboprobe.core.types import JsonValue, Verdict
from roboprobe.experiments.runner import _CampaignRow, build_comparison
from roboprobe.metrics.campaign_metrics import CampaignRun

__all__ = ["ComparisonRuns", "ExperimentSnapshot", "read_campaign_runs", "resolve_comparison"]


class _Run(Protocol):
    id: UUID
    ordinal: int
    repeat_index: int
    verdict: object
    metrics: Mapping[str, JsonValue] | None
    x_unit: Sequence[float] | None
    phase: object
    tags: Sequence[object] | None


class _Page(Protocol):
    @property
    def items(self) -> Sequence[_Run]: ...

    @property
    def next_cursor(self) -> str | None: ...


class ComparisonRuns(Protocol):
    """Run repository read port for experiment comparisons."""

    def list_for_campaign(  # noqa: D102
        self, campaign_id: UUID, *, limit: int | None = None, cursor: str | None = None
    ) -> _Page: ...


class ExperimentSnapshot(Protocol):
    """Stored experiment inputs relevant to a comparison."""

    design: Mapping[str, JsonValue]
    results: Mapping[str, JsonValue] | None


def read_campaign_runs(repository: ComparisonRuns, campaign_id: UUID) -> list[CampaignRun]:
    """Read every adjudicated episode in stable proposal and repeat order."""
    cursor = None
    records: list[_Run] = []
    while True:
        page = repository.list_for_campaign(campaign_id, cursor=cursor)
        records.extend(row for row in page.items if row.verdict is not None)
        cursor = page.next_cursor
        if cursor is None:
            break
    records.sort(key=lambda row: (row.ordinal, row.repeat_index, row.id))
    return [
        CampaignRun(
            verdict=Verdict(str(row.verdict)),
            wall_time_s=float(
                cast(float | int | str, (row.metrics or {}).get("duration_s") or 0.0)
            ),
            x_unit=tuple(float(value) for value in (row.x_unit or ())),
            phase=str(row.phase or ""),
            tags=tuple(str(tag) for tag in (row.tags or ())),
        )
        for row in records
    ]


def _finite_json(value: JsonValue) -> JsonValue:
    if isinstance(value, float) and not isfinite(value):
        return None
    if isinstance(value, list):
        return [_finite_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _finite_json(item) for key, item in value.items()}
    return value


def resolve_comparison(
    experiment_id: UUID,
    experiment: ExperimentSnapshot,
    campaigns: Sequence[_CampaignRow],
    runs_by: Mapping[UUID, Sequence[CampaignRun]],
    settings: ExperimentSettings,
) -> dict[str, JsonValue]:
    """Resolve the same persisted or reproducible comparison for every consumer."""
    results = experiment.results
    if not results and campaigns:
        design = experiment.design
        raw_metrics = design.get("metrics")
        metrics = (
            [item for item in raw_metrics if isinstance(item, str)]
            if isinstance(raw_metrics, list)
            else []
        )
        seeds = design.get("seeds")
        raw_seed = seeds.get("root") if isinstance(seeds, dict) else None
        seed = raw_seed if isinstance(raw_seed, int) else 0
        results = build_comparison(
            experiment_id,
            campaigns,
            runs_by,
            metrics=metrics,
            settings=settings,
            rng=np.random.default_rng(derive_seed(seed, ANALYSIS, "compare")),
        )
    payload: Mapping[str, JsonValue] = results or {}
    return {
        "experiment_id": str(experiment_id),
        "metrics": _finite_json(payload.get("metrics", [])),
        "strategies": _finite_json(payload.get("strategies", {})),
        "tests": _finite_json(payload.get("tests", [])),
    }
