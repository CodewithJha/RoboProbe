"""Outbox topic names and small payload models (docs/12 §4).

Layer: Adapter (infrastructure).
"""

# ruff: noqa: D101

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from roboprobe.core.types import CampaignStatus, FailureClass, JsonValue, Verdict

__all__ = [
    "TOPIC_ALERT",
    "TOPIC_ANALYSIS_FINISHED",
    "TOPIC_CAMPAIGN_UPDATED",
    "TOPIC_MODE_DISCOVERED",
    "TOPIC_RUN_FINISHED",
    "TOPIC_RUN_STARTED",
    "TOPIC_WORKER_UPDATED",
    "AlertPayload",
    "AnalysisFinishedPayload",
    "CampaignUpdatedPayload",
    "ModeDiscoveredPayload",
    "RunFinishedPayload",
    "RunStartedPayload",
    "WorkerUpdatedPayload",
]

TOPIC_CAMPAIGN_UPDATED = "campaign.updated"
TOPIC_RUN_STARTED = "run.started"
TOPIC_RUN_FINISHED = "run.finished"
TOPIC_MODE_DISCOVERED = "mode.discovered"
TOPIC_ANALYSIS_FINISHED = "analysis.finished"
TOPIC_WORKER_UPDATED = "worker.updated"
TOPIC_ALERT = "alert"


class _Payload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CampaignUpdatedPayload(_Payload):
    campaign_id: UUID
    status: CampaignStatus
    counts: dict[str, int] = Field(default_factory=dict)
    modes_found: int = 0


class RunStartedPayload(_Payload):
    run_id: UUID
    campaign_id: UUID
    ordinal: int
    worker_id: str


class RunFinishedPayload(_Payload):
    run_id: UUID
    campaign_id: UUID
    verdict: Verdict | None
    robustness: float | None
    primary_failure: FailureClass | str | None = None
    values: dict[str, JsonValue] = Field(default_factory=dict)


class ModeDiscoveredPayload(_Payload):
    campaign_id: UUID
    mode_id: UUID
    code: str
    label: str
    size: int


class AnalysisFinishedPayload(_Payload):
    campaign_id: UUID
    analysis_id: UUID
    kind: str


class WorkerUpdatedPayload(_Payload):
    worker_id: str
    status: str
    last_heartbeat: datetime


class AlertPayload(_Payload):
    level: Literal["info", "warning", "error"]
    code: str
    message: str
    campaign_id: UUID | None = None
