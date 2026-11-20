"""Campaign lifecycle state machine and ``CampaignService`` commands.

Implements: T-041c, FR-RUN-001, FR-DSH-002
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final
from uuid import UUID

import structlog

from roboprobe.core.errors import ConflictError, ErrorCode, NotFoundError
from roboprobe.core.types import CampaignStatus, JsonValue
from roboprobe.runner.ports import CampaignView, UnitOfWorkPort, UowFactory

__all__ = [
    "ALLOWED",
    "IDEMPOTENT",
    "CampaignCommand",
    "CampaignService",
    "transition",
]

log = structlog.get_logger(__name__)

TOPIC_CAMPAIGN_UPDATED: Final = "campaign.updated"


class CampaignCommand(StrEnum):
    """Lifecycle commands (docs/12 §5) plus internal transitions (docs/14 §3)."""

    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    MARK_ANALYZING = "mark_analyzing"
    COMPLETE = "complete"
    FAIL = "fail"


# (current_status, command) -> new_status
ALLOWED: Final[dict[tuple[CampaignStatus, CampaignCommand], CampaignStatus]] = {
    (CampaignStatus.CREATED, CampaignCommand.START): CampaignStatus.RUNNING,
    (CampaignStatus.PAUSED, CampaignCommand.START): CampaignStatus.RUNNING,
    (CampaignStatus.RUNNING, CampaignCommand.PAUSE): CampaignStatus.PAUSED,
    (CampaignStatus.PAUSED, CampaignCommand.RESUME): CampaignStatus.RUNNING,
    (CampaignStatus.CREATED, CampaignCommand.CANCEL): CampaignStatus.CANCELLED,
    (CampaignStatus.RUNNING, CampaignCommand.CANCEL): CampaignStatus.CANCELLED,
    (CampaignStatus.PAUSED, CampaignCommand.CANCEL): CampaignStatus.CANCELLED,
    (CampaignStatus.RUNNING, CampaignCommand.MARK_ANALYZING): CampaignStatus.ANALYZING,
    (CampaignStatus.COMPLETED, CampaignCommand.MARK_ANALYZING): CampaignStatus.ANALYZING,
    (CampaignStatus.ANALYZING, CampaignCommand.COMPLETE): CampaignStatus.COMPLETED,
    (CampaignStatus.ANALYZING, CampaignCommand.FAIL): CampaignStatus.FAILED,
    (CampaignStatus.RUNNING, CampaignCommand.FAIL): CampaignStatus.FAILED,
}

# Already in the target status: command is a no-op success (docs/12 §5).
IDEMPOTENT: Final[dict[tuple[CampaignStatus, CampaignCommand], CampaignStatus]] = {
    (CampaignStatus.PAUSED, CampaignCommand.PAUSE): CampaignStatus.PAUSED,
    (CampaignStatus.RUNNING, CampaignCommand.START): CampaignStatus.RUNNING,
    (CampaignStatus.RUNNING, CampaignCommand.RESUME): CampaignStatus.RUNNING,
    (CampaignStatus.CANCELLED, CampaignCommand.CANCEL): CampaignStatus.CANCELLED,
    (CampaignStatus.ANALYZING, CampaignCommand.MARK_ANALYZING): CampaignStatus.ANALYZING,
    (CampaignStatus.COMPLETED, CampaignCommand.COMPLETE): CampaignStatus.COMPLETED,
    (CampaignStatus.FAILED, CampaignCommand.FAIL): CampaignStatus.FAILED,
}


def transition(current: CampaignStatus, command: CampaignCommand) -> CampaignStatus:
    """Return the next status for ``command`` from ``current``.

    Args:
        current: Current campaign status.
        command: Lifecycle command.

    Returns:
        The resulting status (unchanged when the command is idempotent).

    Raises:
        ConflictError: Code ``CAMPAIGN_INVALID_TRANSITION`` when the pair is illegal.
    """
    key = (current, command)
    if key in IDEMPOTENT:
        return IDEMPOTENT[key]
    if key in ALLOWED:
        return ALLOWED[key]
    msg = f"Campaign is {current.value}; cannot {command.value}."
    raise ConflictError(
        msg,
        code=ErrorCode.CAMPAIGN_INVALID_TRANSITION,
        context={"from": current.value, "command": command.value},
    )


class CampaignService:
    """Application service mutating campaign status through a UoW port."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Inject a UoW factory (one transaction per command)."""
        self._uow_factory = uow_factory

    def start(self, campaign_id: UUID) -> CampaignStatus:
        """Start or resume a campaign (``CREATED``/``PAUSED`` → ``RUNNING``)."""
        return self._apply(campaign_id, CampaignCommand.START)

    def pause(self, campaign_id: UUID, *, reason: str | None = None) -> CampaignStatus:
        """Pause a running campaign (idempotent on ``PAUSED``)."""
        return self._apply(campaign_id, CampaignCommand.PAUSE, reason=reason)

    def resume(self, campaign_id: UUID) -> CampaignStatus:
        """Resume a paused campaign."""
        return self._apply(campaign_id, CampaignCommand.RESUME)

    def cancel(self, campaign_id: UUID, *, reason: str | None = None) -> CampaignStatus:
        """Cancel a campaign and mark its ``PENDING`` runs ``CANCELLED``."""
        return self._apply(campaign_id, CampaignCommand.CANCEL, reason=reason, cancel_runs=True)

    def mark_analyzing(self, campaign_id: UUID, *, reason: str | None = None) -> CampaignStatus:
        """Move a campaign into ``ANALYZING`` (stop rule or re-analyze)."""
        return self._apply(campaign_id, CampaignCommand.MARK_ANALYZING, reason=reason)

    def complete(self, campaign_id: UUID, *, reason: str | None = None) -> CampaignStatus:
        """Mark analysis done → ``COMPLETED``."""
        return self._apply(campaign_id, CampaignCommand.COMPLETE, reason=reason)

    def fail(self, campaign_id: UUID, *, reason: str | None = None) -> CampaignStatus:
        """Mark the campaign ``FAILED``."""
        return self._apply(campaign_id, CampaignCommand.FAIL, reason=reason)

    def _apply(
        self,
        campaign_id: UUID,
        command: CampaignCommand,
        *,
        reason: str | None = None,
        cancel_runs: bool = False,
    ) -> CampaignStatus:
        with self._uow_factory() as uow:
            campaign = _require(uow, campaign_id)
            previous = campaign.status
            new_status = transition(previous, command)
            if new_status is previous and reason is None:
                # Idempotent no-op: still return current status without events.
                return previous
            uow.campaigns.set_status(campaign_id, new_status, reason=reason)
            cancelled = 0
            if cancel_runs:
                cancelled = uow.runs.cancel_pending(campaign_id)
            payload: dict[str, JsonValue] = {
                "campaign_id": str(campaign_id),
                "status": new_status.value,
                "counts": {"cancelled_pending": cancelled},
                "modes_found": 0,
            }
            uow.events.append(TOPIC_CAMPAIGN_UPDATED, payload, campaign_id=campaign_id)
            uow.commit()
        log.info(
            "campaign.state_changed",
            campaign_id=str(campaign_id),
            from_status=previous.value,
            to_status=new_status.value,
            command=command.value,
            reason=reason,
        )
        return new_status


def _require(uow: UnitOfWorkPort, campaign_id: UUID) -> CampaignView:
    campaign = uow.campaigns.get(campaign_id)
    if campaign is None:
        msg = "campaign not found"
        raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
    return campaign
