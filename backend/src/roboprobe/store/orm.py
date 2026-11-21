"""SQLAlchemy 2 declarative models matching docs/11 §3.

Layer: Adapter (infrastructure). Never imported from domain packages.
Implements: T-010a, FR-STO-001
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, get_args
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    MetaData,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from roboprobe.core.types import CampaignStatus, RunStatus, Severity, Verdict
from roboprobe.store.ids import new_uuid

__all__ = [
    "ANALYSIS_KINDS",
    "ANALYSIS_STATUSES",
    "ARTIFACT_KINDS",
    "EXPERIMENT_STATUSES",
    "FAILURE_MODE_STATUSES",
    "NAMING_CONVENTION",
    "WORKER_STATUSES",
    "AnalysisRow",
    "ArtifactRow",
    "Base",
    "CampaignRow",
    "EventRow",
    "ExperimentRow",
    "FailureModeMemberRow",
    "FailureModeRow",
    "IdempotencyKeyRow",
    "OracleResultRow",
    "RiskMapRow",
    "RunRow",
    "ScenarioSpaceRow",
    "StrategyStateRow",
    "SutProfileRow",
    "WorkerRow",
]

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

EXPERIMENT_STATUSES = ("CREATED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED")
WORKER_STATUSES = ("IDLE", "BUSY", "DRAINING", "OFFLINE", "UNHEALTHY")
ANALYSIS_KINDS = ("incremental", "final", "manual")
ANALYSIS_STATUSES = ("PENDING", "RUNNING", "DONE", "ERROR")
FAILURE_MODE_STATUSES = ("open", "accepted", "fixed", "duplicate")
ARTIFACT_KINDS = (
    "trace",
    "bag",
    "log",
    "world",
    "params",
    "manifest",
    "figure",
    "report",
    "risk_slices",
    "analysis",
    "video",
    "bundle",
)


def _in_sql(column: str, values: tuple[str, ...]) -> str:
    listed = ", ".join(f"'{item}'" for item in values)
    return f"{column} IN ({listed})"


class Base(DeclarativeBase):
    """Declarative base with stable constraint names for Alembic."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class ScenarioSpaceRow(Base):
    """``scenario_spaces``."""

    __tablename__ = "scenario_spaces"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class SutProfileRow(Base):
    """``sut_profiles``."""

    __tablename__ = "sut_profiles"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    backend: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ExperimentRow(Base):
    """``experiments``."""

    __tablename__ = "experiments"
    __table_args__ = (CheckConstraint(_in_sql("status", EXPERIMENT_STATUSES), name="status"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    design: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    results: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CampaignRow(Base):
    """``campaigns``."""

    __tablename__ = "campaigns"
    __table_args__ = (
        ForeignKeyConstraint(
            ["space_id", "space_version"],
            ["scenario_spaces.id", "scenario_spaces.version"],
        ),
        CheckConstraint(
            _in_sql("status", tuple(s.value for s in CampaignStatus)),
            name="status",
        ),
        CheckConstraint("budget > 0", name="budget_positive"),
        CheckConstraint("repeats >= 1", name="repeats_min"),
        CheckConstraint("batch_size >= 1", name="batch_size_min"),
        Index("ix_campaigns_status", "status"),
        Index("ix_campaigns_experiment", "experiment_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    space_id: Mapped[str] = mapped_column(Text, nullable=False)
    space_version: Mapped[str] = mapped_column(Text, nullable=False)
    sut_profile_id: Mapped[str] = mapped_column(Text, ForeignKey("sut_profiles.id"), nullable=False)
    backend: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_id: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    budget: Mapped[int] = mapped_column(Integer, nullable=False)
    repeats: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    pins: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    oracle_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    stop_rules: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    status_reason: Mapped[str | None] = mapped_column(Text)
    experiment_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("experiments.id", ondelete="SET NULL")
    )
    experiment_rep: Mapped[int | None] = mapped_column(Integer)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    etag_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class WorkerRow(Base):
    """``workers``."""

    __tablename__ = "workers"
    __table_args__ = (CheckConstraint(_in_sql("status", WORKER_STATUSES), name="status"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    backend: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    current_run_id: Mapped[UUID | None] = mapped_column(Uuid)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_heartbeat: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class RunRow(Base):
    """``runs``."""

    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("campaign_id", "ordinal", "repeat_index"),
        CheckConstraint(_in_sql("status", tuple(s.value for s in RunStatus)), name="status"),
        CheckConstraint(
            "verdict IS NULL OR " + _in_sql("verdict", tuple(s.value for s in Verdict)),
            name="verdict",
        ),
        CheckConstraint(
            "robustness IS NULL OR (robustness BETWEEN -1 AND 1)",
            name="robustness_range",
        ),
        Index(
            "ix_runs_queue",
            "backend",
            "priority",
            "enqueued_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index("ix_runs_campaign_status", "campaign_id", "status"),
        Index("ix_runs_campaign_verdict", "campaign_id", "verdict"),
        Index("ix_runs_scenario_hash", "scenario_hash"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    campaign_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    repeat_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    backend: Mapped[str] = mapped_column(Text, nullable=False)
    scenario_hash: Mapped[str] = mapped_column(Text, nullable=False)
    scenario_values: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    x_unit: Mapped[list[float]] = mapped_column(ARRAY(Double), nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    proposal: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    replay_of: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("runs.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    worker_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("workers.id", ondelete="SET NULL")
    )
    verdict: Mapped[str | None] = mapped_column(Text)
    robustness: Mapped[float | None] = mapped_column(Double)
    primary_failure: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    infra_error: Mapped[str | None] = mapped_column(Text)
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    enqueued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OracleResultRow(Base):
    """``oracle_results``."""

    __tablename__ = "oracle_results"
    __table_args__ = (CheckConstraint(_in_sql("severity", get_args(Severity)), name="severity"),)

    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    oracle_id: Mapped[str] = mapped_column(Text, primary_key=True)
    failure_class: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    violated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    robustness: Mapped[float] = mapped_column(Double, nullable=False)
    first_violation_t: Mapped[float | None] = mapped_column(Double)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class StrategyStateRow(Base):
    """``strategy_states``."""

    __tablename__ = "strategy_states"

    campaign_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True
    )
    n_obs: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AnalysisRow(Base):
    """``analyses``."""

    __tablename__ = "analyses"
    __table_args__ = (
        CheckConstraint(_in_sql("kind", ANALYSIS_KINDS), name="kind"),
        CheckConstraint(_in_sql("status", ANALYSIS_STATUSES), name="status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    campaign_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    n_runs: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    report_sha256: Mapped[str | None] = mapped_column(Text)
    analysis_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FailureModeRow(Base):
    """``failure_modes``."""

    __tablename__ = "failure_modes"
    __table_args__ = (
        UniqueConstraint("campaign_id", "code"),
        CheckConstraint(_in_sql("status", FAILURE_MODE_STATUSES), name="status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    campaign_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    label_is_user: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    primary_class: Mapped[str] = mapped_column(Text, nullable=False)
    class_mix: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    param_ranges: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    characteristic: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    medoid_run_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("runs.id"))
    minimal_run_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("runs.id"))
    rules: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    interaction: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reproducibility: Mapped[float | None] = mapped_column(Double)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"))
    first_seen_run: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("runs.id"))
    analysis_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("analyses.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    etag_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class FailureModeMemberRow(Base):
    """``failure_mode_members``."""

    __tablename__ = "failure_mode_members"

    mode_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("failure_modes.id", ondelete="CASCADE"), primary_key=True
    )
    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    membership: Mapped[float] = mapped_column(Double, nullable=False)


class RiskMapRow(Base):
    """``risk_maps``."""

    __tablename__ = "risk_maps"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    campaign_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    analysis_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("analyses.id"))
    n_obs: Mapped[int] = mapped_column(Integer, nullable=False)
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    volumes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    robustness_score: Mapped[float] = mapped_column(Double, nullable=False)
    slices_artifact: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ArtifactRow(Base):
    """``artifacts``."""

    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint(_in_sql("kind", ARTIFACT_KINDS), name="kind"),
        Index("ix_artifacts_run", "run_id"),
        Index("ix_artifacts_sha", "sha256"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    run_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("runs.id", ondelete="CASCADE"))
    campaign_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("campaigns.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rel_path: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class EventRow(Base):
    """``events`` transactional outbox."""

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_campaign", "campaign_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    campaign_id: Mapped[UUID | None] = mapped_column(Uuid)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class IdempotencyKeyRow(Base):
    """``idempotency_keys`` — cached POST responses (docs/12 §1)."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (Index("ix_idempotency_keys_created", "created_at"),)

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    body_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
