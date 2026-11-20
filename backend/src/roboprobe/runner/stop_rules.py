"""Campaign stop rules and auto-pause predicates (Specification pattern).

Implements: T-042b, FR-RUN-002
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from roboprobe.core.settings.runner import AutoPauseSettings, RunnerSettings
from roboprobe.core.types import RunStatus, Verdict

__all__ = [
    "CampaignCounters",
    "StopDecision",
    "StopRule",
    "budget_exhausted",
    "counters_from_runs",
    "evaluate_stop_rules",
    "invalid_ratio_pause",
    "max_consecutive_invalid_pause",
    "max_modes_reached",
    "max_wall_reached",
]


class _RunLike(Protocol):
    status: object
    verdict: object


@dataclass(frozen=True, slots=True)
class CampaignCounters:
    """Snapshot of campaign progress used by stop/auto-pause rules."""

    budget: int
    finished: int
    invalid: int
    consecutive_invalid: int
    modes_found: int
    started_at: datetime | None
    now: datetime
    stop_rules: dict[str, object]


@dataclass(frozen=True, slots=True)
class StopDecision:
    """Result of evaluating stop/auto-pause rules."""

    action: str  # "continue" | "analyze" | "pause"
    reason: str | None = None
    code: str | None = None


class StopRule(Protocol):
    """Pure predicate over :class:`CampaignCounters`."""

    def evaluate(self, counters: CampaignCounters) -> StopDecision | None:
        """Return a decision if this rule fires, else ``None``."""
        ...


def budget_exhausted(counters: CampaignCounters) -> StopDecision | None:
    """Stop when finished runs reach the campaign budget."""
    if counters.finished >= counters.budget:
        return StopDecision(action="analyze", reason="budget", code="BUDGET_EXHAUSTED")
    return None


def max_modes_reached(counters: CampaignCounters) -> StopDecision | None:
    """Stop when ``stop_rules.max_modes`` is set and reached."""
    raw = counters.stop_rules.get("max_modes")
    if raw is None:
        return None
    if not isinstance(raw, (int, float, str)):
        return None
    limit = int(raw)
    if counters.modes_found >= limit:
        return StopDecision(action="analyze", reason="max_modes", code="MAX_MODES")
    return None


def max_wall_reached(counters: CampaignCounters) -> StopDecision | None:
    """Stop when wall time since ``started_at`` exceeds ``stop_rules.max_wall_s``."""
    raw = counters.stop_rules.get("max_wall_s")
    if raw is None or counters.started_at is None:
        return None
    if not isinstance(raw, (int, float, str)):
        return None
    limit_s = float(raw)
    elapsed = (counters.now - counters.started_at).total_seconds()
    if elapsed >= limit_s:
        return StopDecision(action="analyze", reason="max_wall_s", code="MAX_WALL")
    return None


def invalid_ratio_pause(
    counters: CampaignCounters, settings: AutoPauseSettings
) -> StopDecision | None:
    """Auto-pause when INVALID ratio exceeds the threshold after ``min_runs``."""
    if counters.finished < settings.min_runs:
        return None
    if counters.finished == 0:
        return None
    ratio = counters.invalid / counters.finished
    if ratio > settings.invalid_ratio:
        return StopDecision(action="pause", reason="invalid_ratio", code="INFRA_UNHEALTHY")
    return None


def max_consecutive_invalid_pause(
    counters: CampaignCounters, settings: AutoPauseSettings
) -> StopDecision | None:
    """Auto-pause when consecutive INVALID runs reach the configured cap."""
    # Campaign stop_rules may override the default.
    raw = counters.stop_rules.get("max_consecutive_invalid")
    if raw is None:
        limit = settings.max_consecutive_invalid
    elif isinstance(raw, (int, float, str)):
        limit = int(raw)
    else:
        limit = settings.max_consecutive_invalid
    if counters.consecutive_invalid >= limit:
        return StopDecision(
            action="pause",
            reason="max_consecutive_invalid",
            code="INFRA_UNHEALTHY",
        )
    return None


def evaluate_stop_rules(counters: CampaignCounters, settings: RunnerSettings) -> StopDecision:
    """Evaluate stop then auto-pause rules; first match wins."""
    for rule in (budget_exhausted, max_modes_reached, max_wall_reached):
        decision = rule(counters)
        if decision is not None:
            return decision
    for rule in (
        lambda c: invalid_ratio_pause(c, settings.auto_pause),
        lambda c: max_consecutive_invalid_pause(c, settings.auto_pause),
    ):
        decision = rule(counters)
        if decision is not None:
            return decision
    return StopDecision(action="continue")


def counters_from_runs(  # noqa: PLR0913 - counters need the full campaign snapshot
    *,
    budget: int,
    runs: Sequence[_RunLike],
    modes_found: int,
    started_at: datetime | None,
    now: datetime,
    stop_rules: dict[str, object],
) -> CampaignCounters:
    """Derive counters from run rows (INVALID = ERROR or DONE+INVALID verdict)."""
    finished = 0
    invalid = 0
    consecutive = 0
    streak = 0
    ordered = list(runs)
    for run in ordered:
        status = run.status if isinstance(run.status, RunStatus) else RunStatus(str(run.status))
        verdict = run.verdict
        if isinstance(verdict, str):
            verdict = Verdict(verdict)
        is_terminal = status in {RunStatus.DONE, RunStatus.ERROR, RunStatus.CANCELLED}
        if not is_terminal:
            continue
        if status is RunStatus.CANCELLED:
            streak = 0
            continue
        finished += 1
        is_invalid = status is RunStatus.ERROR or verdict is Verdict.INVALID
        if is_invalid:
            invalid += 1
            streak += 1
            consecutive = max(consecutive, streak)
        else:
            streak = 0
    return CampaignCounters(
        budget=budget,
        finished=finished,
        invalid=invalid,
        consecutive_invalid=streak,
        modes_found=modes_found,
        started_at=started_at,
        now=now,
        stop_rules=stop_rules,
    )
