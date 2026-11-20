"""ORM row → frozen record converters."""

# ruff: noqa: D103

from __future__ import annotations

from typing import cast

from pydantic import JsonValue

from roboprobe.core.types import CampaignStatus, RunStatus, Verdict
from roboprobe.store.orm import (
    AnalysisRow,
    ArtifactRow,
    CampaignRow,
    EventRow,
    ExperimentRow,
    FailureModeMemberRow,
    FailureModeRow,
    OracleResultRow,
    RiskMapRow,
    RunRow,
    ScenarioSpaceRow,
    StrategyStateRow,
    SutProfileRow,
    WorkerRow,
)
from roboprobe.store.records import (
    AnalysisRecord,
    ArtifactRecord,
    CampaignRecord,
    EventRecord,
    ExperimentRecord,
    FailureModeMemberRecord,
    FailureModeRecord,
    OracleResultRecord,
    RiskMapRecord,
    RunRecord,
    SpaceRecord,
    StrategyStateRecord,
    SutProfileRecord,
    WorkerRecord,
)


def _json(value: object) -> dict[str, JsonValue]:
    return cast("dict[str, JsonValue]", value or {})


def space_record(row: ScenarioSpaceRow) -> SpaceRecord:
    return SpaceRecord(
        id=row.id,
        version=row.version,
        name=row.name,
        definition=_json(row.definition),
        schema_version=row.schema_version,
        created_at=row.created_at,
    )


def sut_record(row: SutProfileRow) -> SutProfileRecord:
    return SutProfileRecord(
        id=row.id,
        backend=row.backend,
        config=_json(row.config),
        config_hash=row.config_hash,
        created_at=row.created_at,
    )


def experiment_record(row: ExperimentRow) -> ExperimentRecord:
    return ExperimentRecord(
        id=row.id,
        name=row.name,
        design=_json(row.design),
        status=row.status,
        results=None if row.results is None else _json(row.results),
        created_at=row.created_at,
        finished_at=row.finished_at,
    )


def campaign_record(row: CampaignRow) -> CampaignRecord:
    return CampaignRecord(
        id=row.id,
        name=row.name,
        space_id=row.space_id,
        space_version=row.space_version,
        sut_profile_id=row.sut_profile_id,
        backend=row.backend,
        strategy_id=row.strategy_id,
        strategy_params=_json(row.strategy_params),
        seed=row.seed,
        budget=row.budget,
        repeats=row.repeats,
        batch_size=row.batch_size,
        pins=_json(row.pins),
        oracle_config=_json(row.oracle_config),
        stop_rules=_json(row.stop_rules),
        status=CampaignStatus(row.status),
        status_reason=row.status_reason,
        experiment_id=row.experiment_id,
        experiment_rep=row.experiment_rep,
        tags=tuple(row.tags or ()),
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def run_record(row: RunRow) -> RunRecord:
    return RunRecord(
        id=row.id,
        campaign_id=row.campaign_id,
        ordinal=row.ordinal,
        repeat_index=row.repeat_index,
        backend=row.backend,
        scenario_hash=row.scenario_hash,
        scenario_values=_json(row.scenario_values),
        x_unit=tuple(row.x_unit or ()),
        seed=row.seed,
        phase=row.phase,
        proposal=_json(row.proposal),
        tags=tuple(row.tags or ()),
        replay_of=row.replay_of,
        status=RunStatus(row.status),
        priority=row.priority,
        attempt=row.attempt,
        worker_id=row.worker_id,
        verdict=None if row.verdict is None else Verdict(row.verdict),
        robustness=row.robustness,
        primary_failure=row.primary_failure,
        warnings=tuple(row.warnings or ()),
        metrics=_json(row.metrics),
        infra_error=row.infra_error,
        manifest=None if row.manifest is None else _json(row.manifest),
        enqueued_at=row.enqueued_at,
        claimed_at=row.claimed_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def oracle_record(row: OracleResultRow) -> OracleResultRecord:
    return OracleResultRecord(
        run_id=row.run_id,
        oracle_id=row.oracle_id,
        failure_class=row.failure_class,
        severity=row.severity,
        violated=row.violated,
        robustness=row.robustness,
        first_violation_t=row.first_violation_t,
        details=_json(row.details),
    )


def strategy_record(row: StrategyStateRow) -> StrategyStateRecord:
    return StrategyStateRecord(
        campaign_id=row.campaign_id,
        n_obs=row.n_obs,
        state=_json(row.state),
        updated_at=row.updated_at,
    )


def analysis_record(row: AnalysisRow) -> AnalysisRecord:
    return AnalysisRecord(
        id=row.id,
        campaign_id=row.campaign_id,
        kind=row.kind,
        status=row.status,
        n_runs=row.n_runs,
        summary=None if row.summary is None else _json(row.summary),
        report_sha256=row.report_sha256,
        analysis_schema_version=row.analysis_schema_version,
        created_at=row.created_at,
        finished_at=row.finished_at,
    )


def mode_record(row: FailureModeRow) -> FailureModeRecord:
    rules = list(row.rules)
    return FailureModeRecord(
        id=row.id,
        campaign_id=row.campaign_id,
        code=row.code,
        label=row.label,
        label_is_user=row.label_is_user,
        primary_class=row.primary_class,
        class_mix=_json(row.class_mix),
        size=row.size,
        param_ranges=_json(row.param_ranges),
        characteristic=tuple(row.characteristic or ()),
        medoid_run_id=row.medoid_run_id,
        minimal_run_id=row.minimal_run_id,
        rules=rules,
        interaction=None if row.interaction is None else _json(row.interaction),
        reproducibility=row.reproducibility,
        status=row.status,
        first_seen_run=row.first_seen_run,
        analysis_id=row.analysis_id,
        updated_at=row.updated_at,
    )


def member_record(row: FailureModeMemberRow) -> FailureModeMemberRecord:
    return FailureModeMemberRecord(
        mode_id=row.mode_id, run_id=row.run_id, membership=row.membership
    )


def risk_record(row: RiskMapRow) -> RiskMapRecord:
    return RiskMapRecord(
        id=row.id,
        campaign_id=row.campaign_id,
        analysis_id=row.analysis_id,
        n_obs=row.n_obs,
        thresholds=_json(row.thresholds),
        volumes=_json(row.volumes),
        robustness_score=row.robustness_score,
        slices_artifact=row.slices_artifact,
        created_at=row.created_at,
    )


def artifact_record(row: ArtifactRow) -> ArtifactRecord:
    return ArtifactRecord(
        id=row.id,
        run_id=row.run_id,
        campaign_id=row.campaign_id,
        kind=row.kind,
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        rel_path=row.rel_path,
        media_type=row.media_type,
        created_at=row.created_at,
    )


def worker_record(row: WorkerRow) -> WorkerRecord:
    return WorkerRecord(
        id=row.id,
        backend=row.backend,
        status=row.status,
        capabilities=_json(row.capabilities),
        version=row.version,
        current_run_id=row.current_run_id,
        started_at=row.started_at,
        last_heartbeat=row.last_heartbeat,
    )


def event_record(row: EventRow) -> EventRecord:
    return EventRecord(
        id=row.id,
        topic=row.topic,
        campaign_id=row.campaign_id,
        payload=_json(row.payload),
        created_at=row.created_at,
    )
