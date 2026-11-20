"""Enqueue and summarise replay runs (docs/14 §7, FR-REP-001).

Implements: T-044, FR-REP-001, NFR-REP-001
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.core.seeding import derive_seed
from roboprobe.core.types import JsonValue, RunStatus, Verdict
from roboprobe.runner.ports import UowFactory

__all__ = [
    "REPLAY_PHASE",
    "REPLAY_PRIORITY",
    "ReplayAgreement",
    "ReplayRequest",
    "enqueue_replays",
    "summarise_agreement",
]

REPLAY_PHASE = "replay"
REPLAY_PRIORITY = 10
_REPLAY_STREAM = "replay"


@dataclass(frozen=True, slots=True)
class ReplayRequest:
    """How to enqueue replays of a source run."""

    run_id: UUID
    repeats: int = 1
    fresh_seeds: bool = False


@dataclass(frozen=True, slots=True)
class ReplayAgreement:
    """Verdict / class / optional trace-hash agreement summary."""

    source_run_id: UUID
    replay_ids: tuple[UUID, ...]
    source_verdict: str | None
    source_failure: str | None
    agreements: int
    disagreements: int
    trace_matches: int | None
    rows: tuple[dict[str, JsonValue], ...]

    @property
    def all_agree(self) -> bool:
        """True when every replay matched the source verdict and primary failure."""
        return self.disagreements == 0 and self.agreements == len(self.replay_ids)


def enqueue_replays(uow_factory: UowFactory, request: ReplayRequest) -> tuple[UUID, ...]:
    """Insert ``repeats`` PENDING replay runs copying the source scenario.

    Raises:
        NotFoundError: Source run missing.
        ValidationError: Source run is not finished (DONE).
    """
    if request.repeats < 1:
        msg = "repeats must be >= 1"
        raise ValidationError(msg, context={"repeats": request.repeats})
    records = importlib.import_module("roboprobe.store.records")
    with uow_factory() as uow:
        source = uow.runs.get(request.run_id)
        if source is None:
            msg = "run not found"
            raise NotFoundError(msg, context={"run_id": str(request.run_id)})
        status = (
            source.status if isinstance(source.status, RunStatus) else RunStatus(str(source.status))
        )
        if status is not RunStatus.DONE:
            msg = "only DONE runs can be replayed"
            raise ValidationError(
                msg, context={"run_id": str(request.run_id), "status": status.value}
            )
        campaign = uow.campaigns.get(source.campaign_id)
        if campaign is None:
            msg = "campaign not found for run"
            raise NotFoundError(msg, context={"campaign_id": str(source.campaign_id)})
        # Walk pages for the true max ordinal.
        max_ordinal = source.ordinal
        cursor: str | None = None
        while True:
            page = cast(
                Any, uow.runs.list_for_campaign(source.campaign_id, limit=None, cursor=cursor)
            )
            for row in page.items:
                max_ordinal = max(max_ordinal, int(row.ordinal))
            cursor = page.next_cursor
            if cursor is None:
                break
        new_runs = []
        for index in range(request.repeats):
            seed = (
                derive_seed(int(source.seed), _REPLAY_STREAM, index)
                if request.fresh_seeds
                else int(source.seed)
            )
            new_runs.append(
                records.NewRun(
                    campaign_id=source.campaign_id,
                    ordinal=max_ordinal + 1 + index,
                    repeat_index=0,
                    backend=source.backend,
                    scenario_hash=source.scenario_hash,
                    scenario_values=dict(source.scenario_values),
                    x_unit=tuple(source.x_unit),
                    seed=seed,
                    phase=REPLAY_PHASE,
                    proposal={"replay_of": str(source.id), "fresh_seeds": request.fresh_seeds},
                    tags=("replay",),
                    replay_of=source.id,
                    priority=REPLAY_PRIORITY,
                )
            )
        ids = uow.runs.insert_batch(new_runs)
        uow.commit()
    return ids


def summarise_agreement(
    uow_factory: UowFactory,
    source_run_id: UUID,
    replay_ids: tuple[UUID, ...],
    *,
    trace_hashes: dict[UUID, str] | None = None,
) -> ReplayAgreement:
    """Compare replay verdicts (and optional trace hashes) to the source run."""
    with uow_factory() as uow:
        source = uow.runs.get(source_run_id)
        if source is None:
            msg = "run not found"
            raise NotFoundError(msg, context={"run_id": str(source_run_id)})
        source_verdict = _verdict_str(source.verdict)
        source_failure = getattr(source, "primary_failure", None)
        source_trace = None if trace_hashes is None else trace_hashes.get(source_run_id)
        rows: list[dict[str, JsonValue]] = []
        agreements = 0
        disagreements = 0
        trace_matches = 0 if trace_hashes is not None else None
        for rid in replay_ids:
            run = uow.runs.get(rid)
            if run is None:
                rows.append({"run_id": str(rid), "status": "missing", "agree": False})
                disagreements += 1
                continue
            verdict = _verdict_str(run.verdict)
            failure = getattr(run, "primary_failure", None)
            agree = verdict == source_verdict and failure == source_failure
            if agree:
                agreements += 1
            else:
                disagreements += 1
            trace_ok: bool | None = None
            if trace_hashes is not None and source_trace is not None:
                replay_trace = trace_hashes.get(rid)
                trace_ok = replay_trace == source_trace
                if trace_ok:
                    trace_matches = (trace_matches or 0) + 1
            rows.append(
                {
                    "run_id": str(rid),
                    "verdict": verdict,
                    "primary_failure": failure,
                    "agree": agree,
                    "trace_match": trace_ok,
                }
            )
    return ReplayAgreement(
        source_run_id=source_run_id,
        replay_ids=replay_ids,
        source_verdict=source_verdict,
        source_failure=source_failure,
        agreements=agreements,
        disagreements=disagreements,
        trace_matches=trace_matches,
        rows=tuple(rows),
    )


def _verdict_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Verdict):
        return value.value
    return str(value)
