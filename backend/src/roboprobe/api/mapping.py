"""Map persistence records to API DTOs (no ORM in responses).

Implements: T-081, T-082, T-084
"""

# ruff: noqa: D103

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from roboprobe.api.schemas import (
    ArtifactOut,
    CampaignOut,
    ExperimentOut,
    FailureModeOut,
    RiskOut,
    RunOut,
    SpaceOut,
    SpaceRef,
    StrategyRef,
    SutProfileOut,
    WorkerOut,
)
from roboprobe.core.types import CampaignStatus, RunStatus, Verdict
from roboprobe.runner.manifest import hash_hostname

__all__ = [
    "artifact_out",
    "campaign_counts",
    "campaign_out",
    "experiment_out",
    "failure_mode_out",
    "risk_out",
    "run_out",
    "space_out",
    "sut_out",
    "worker_out",
]

_TERMINAL = frozenset({CampaignStatus.COMPLETED, CampaignStatus.FAILED, CampaignStatus.CANCELLED})


def _enum_value(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def campaign_out(
    record: Any,
    *,
    base_path: str,
    counts: dict[str, int] | None = None,
) -> CampaignOut:
    """Build ``Campaign`` DTO."""
    cid = record.id
    prefix = base_path.rstrip("/")
    return CampaignOut(
        id=cid,
        name=record.name,
        status=record.status
        if isinstance(record.status, CampaignStatus)
        else CampaignStatus(str(record.status)),
        backend=record.backend,
        strategy=StrategyRef(
            id=record.strategy_id,
            seed=record.seed,
            params={
                key: value
                for key, value in record.strategy_params.items()
                if key != "_resolved_settings"
            },
        ),
        budget=record.budget,
        repeats=record.repeats,
        batch_size=record.batch_size,
        counts=counts or {},
        modes_found=int(counts.get("modes_found", 0)) if counts else 0,
        first_failure_at=counts.get("first_failure_at") if counts else None,
        tags=list(record.tags),
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        links={
            "self": f"{prefix}/campaigns/{cid}",
            "runs": f"{prefix}/campaigns/{cid}/runs",
        },
        pins=dict(getattr(record, "pins", {}) or {}),
        space=(
            SpaceRef(id=record.space_id, version=record.space_version)
            if getattr(record, "space_id", None) is not None
            else None
        ),
    )


def campaign_counts(runs: list[Any], *, budget: int) -> dict[str, int]:
    """Aggregate run counters for a campaign."""
    out = {
        "pending": 0,
        "running": 0,
        "done": 0,
        "pass": 0,
        "fail": 0,
        "invalid": 0,
        "budget": budget,
    }
    for run in runs:
        status = run.status if isinstance(run.status, RunStatus) else RunStatus(str(run.status))
        if status is RunStatus.PENDING:
            out["pending"] += 1
        elif status is RunStatus.RUNNING:
            out["running"] += 1
        elif status is RunStatus.DONE:
            out["done"] += 1
            verdict = None if run.verdict is None else Verdict(_enum_value(run.verdict))
            if verdict is Verdict.PASS:
                out["pass"] += 1
            elif verdict is Verdict.FAIL:
                out["fail"] += 1
                out["first_failure_at"] = min(out.get("first_failure_at", run.ordinal), run.ordinal)
            elif verdict is Verdict.INVALID:
                out["invalid"] += 1
    return out


def run_out(record: Any, *, oracles: list[dict[str, object]] | None = None) -> RunOut:
    """Build ``Run`` DTO."""
    verdict = None if record.verdict is None else _enum_value(record.verdict)
    return RunOut(
        id=record.id,
        campaign_id=record.campaign_id,
        ordinal=record.ordinal,
        repeat_index=record.repeat_index,
        status=_enum_value(record.status),
        phase=record.phase,
        manifest=getattr(record, "manifest", None),
        scenario={
            "hash": record.scenario_hash,
            "values": dict(record.scenario_values),
        },
        proposal=dict(record.proposal),
        seed=record.seed,
        verdict=verdict,
        robustness=record.robustness,
        primary_failure=record.primary_failure,
        warnings=list(record.warnings),
        oracles=oracles or [],
        metrics=dict(record.metrics),
        worker_id=record.worker_id,
        timing={
            "enqueued_at": record.enqueued_at,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
        },
        tags=list(record.tags),
    )


def space_out(record: Any) -> SpaceOut:
    return SpaceOut(
        id=record.id,
        version=record.version,
        name=record.name,
        schema_version=record.schema_version,
        created_at=record.created_at,
    )


def sut_out(record: Any) -> SutProfileOut:
    return SutProfileOut(
        id=record.id,
        backend=record.backend,
        config_hash=record.config_hash,
        created_at=record.created_at,
    )


def failure_mode_out(
    record: Any, *, provisional: bool = False, first_seen_ordinal: int | None = None
) -> FailureModeOut:
    return FailureModeOut(
        id=record.id,
        campaign_id=record.campaign_id,
        code=record.code,
        label=record.label,
        label_is_user=getattr(record, "label_is_user", False),
        provisional=provisional,
        first_seen_ordinal=first_seen_ordinal,
        reproducibility=getattr(record, "reproducibility", None),
        version=getattr(record, "etag_version", 1),
        duplicate_of=getattr(record, "duplicate_of", None),
        param_ranges=dict(getattr(record, "param_ranges", {})),
        characteristic=list(getattr(record, "characteristic", ())),
        rules=list(getattr(record, "rules", ())),
        medoid_run_id=getattr(record, "medoid_run_id", None),
        minimal_run_id=getattr(record, "minimal_run_id", None),
        size=record.size,
        primary_class=record.primary_class,
        status=record.status,
        interaction=None if record.interaction is None else dict(record.interaction),
    )


def risk_out(record: Any, *, campaign_id: UUID) -> RiskOut:
    return RiskOut(
        campaign_id=campaign_id,
        robustness_score=record.robustness_score,
        volumes=dict(record.volumes),
        thresholds=dict(record.thresholds),
    )


def experiment_out(record: Any) -> ExperimentOut:
    return ExperimentOut(
        id=record.id,
        notes=getattr(record, "notes", None),
        version=getattr(record, "etag_version", 1),
        name=record.name,
        status=record.status,
        design=dict(record.design),
        results=None if record.results is None else dict(record.results),
        created_at=record.created_at,
        finished_at=record.finished_at,
    )


def artifact_out(record: Any) -> ArtifactOut:
    return ArtifactOut(
        id=record.id,
        kind=record.kind,
        sha256=record.sha256,
        size_bytes=record.size_bytes,
        media_type=record.media_type,
    )


def worker_out(record: Any, *, now: datetime) -> WorkerOut:
    raw_id = str(record.id)
    parts = raw_id.rsplit(":", 2)
    host = parts[0] if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit() else raw_id
    last_heartbeat = record.last_heartbeat
    heartbeat_age = (
        None if last_heartbeat is None else max(0.0, (now - last_heartbeat).total_seconds())
    )
    return WorkerOut(
        id=f"worker-{hash_hostname(raw_id)}",
        backend=record.backend,
        status=record.status,
        version=record.version,
        current_run_id=record.current_run_id,
        last_heartbeat=last_heartbeat,
        heartbeat_age_s=heartbeat_age,
        host_hash=hash_hostname(host),
    )
