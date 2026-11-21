"""Run repository."""

# ruff: noqa: D102, D107

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from roboprobe.core.types import FailureClass, Observation, RunStatus, Verdict
from roboprobe.store.flush import execute
from roboprobe.store.ids import new_uuid
from roboprobe.store.mapping import run_record
from roboprobe.store.orm import RunRow
from roboprobe.store.pagination import Page, clamp_limit, extra_item
from roboprobe.store.records import NewRun, RunRecord
from roboprobe.store.run_queries import RunSort, query_runs


class SqlRunRepo:
    """Implements: RunRepo."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, run_id: UUID) -> RunRecord | None:
        row = self._s.get(RunRow, run_id)
        return None if row is None else run_record(row)

    def insert_batch(self, runs: Sequence[NewRun]) -> tuple[UUID, ...]:
        if not runs:
            return ()
        ids: list[UUID] = []
        payload: list[dict[str, object]] = []
        for item in runs:
            run_id = item.id or new_uuid()
            ids.append(run_id)
            payload.append(
                {
                    "id": run_id,
                    "campaign_id": item.campaign_id,
                    "ordinal": item.ordinal,
                    "repeat_index": item.repeat_index,
                    "backend": item.backend,
                    "scenario_hash": item.scenario_hash,
                    "scenario_values": dict(item.scenario_values),
                    "x_unit": list(item.x_unit),
                    "seed": item.seed,
                    "phase": item.phase,
                    "proposal": dict(item.proposal),
                    "tags": list(item.tags),
                    "replay_of": item.replay_of,
                    "status": "PENDING",
                    "priority": item.priority,
                }
            )
        stmt = (
            insert(RunRow)
            .values(payload)
            .on_conflict_do_nothing(index_elements=["campaign_id", "ordinal", "repeat_index"])
        )
        execute(self._s, stmt)
        return tuple(ids)

    def import_many(self, runs: Sequence[RunRecord]) -> None:
        if not runs:
            return
        for item in runs:
            values: dict[str, object] = {
                "id": item.id,
                "campaign_id": item.campaign_id,
                "ordinal": item.ordinal,
                "repeat_index": item.repeat_index,
                "backend": item.backend,
                "scenario_hash": item.scenario_hash,
                "scenario_values": dict(item.scenario_values),
                "x_unit": list(item.x_unit),
                "seed": item.seed,
                "phase": item.phase,
                "proposal": dict(item.proposal),
                "tags": list(item.tags),
                "replay_of": item.replay_of,
                "status": item.status.value,
                "priority": item.priority,
                "attempt": item.attempt,
                # Workers are host-local; drop FK on import.
                "worker_id": None,
                "verdict": None if item.verdict is None else item.verdict.value,
                "robustness": item.robustness,
                "primary_failure": item.primary_failure,
                "warnings": list(item.warnings),
                "metrics": dict(item.metrics),
                "infra_error": item.infra_error,
                "manifest": None if item.manifest is None else dict(item.manifest),
                "claimed_at": item.claimed_at,
                "started_at": item.started_at,
                "finished_at": item.finished_at,
            }
            if item.enqueued_at is not None:
                values["enqueued_at"] = item.enqueued_at
            self._s.add(RunRow(**values))
        self._s.flush()

    def list_for_campaign(
        self, campaign_id: UUID, *, limit: int | None = None, cursor: str | None = None
    ) -> Page[RunRecord]:
        size = clamp_limit(limit)
        stmt = select(RunRow).where(RunRow.campaign_id == campaign_id).order_by(RunRow.id)
        if cursor is not None:
            stmt = stmt.where(RunRow.id > UUID(cursor))
        rows = self._s.scalars(stmt.limit(size + 1)).all()
        items, extra = extra_item([run_record(r) for r in rows], size)
        nxt = None if extra is None else str(items[-1].id)
        return Page(items=items, next_cursor=nxt)

    def query_for_campaign(  # noqa: PLR0913 - explicit run filters
        self,
        campaign_id: UUID,
        *,
        limit: int,
        cursor: str | None = None,
        sort: RunSort = "ordinal",
        status: str | None = None,
        verdict: str | None = None,
        phase: str | None = None,
        failure_class: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> Page[RunRecord]:
        return query_runs(
            self._s,
            campaign_id,
            limit=limit,
            cursor=cursor,
            sort=sort,
            status=status,
            verdict=verdict,
            phase=phase,
            failure_class=failure_class,
            tags=tags,
        )

    def history(
        self,
        campaign_id: UUID,
        *,
        exclude_phases: frozenset[str] | None = None,
    ) -> list[Observation]:
        skipped = frozenset({"confirm", "manual"}) if exclude_phases is None else exclude_phases
        rows = self._s.scalars(
            select(RunRow)
            .where(
                RunRow.campaign_id == campaign_id,
                RunRow.status == "DONE",
                RunRow.verdict.is_not(None),
                RunRow.verdict != Verdict.INVALID.value,
            )
            .order_by(RunRow.ordinal, RunRow.repeat_index)
        ).all()
        out: list[Observation] = []
        for row in rows:
            if row.phase in skipped:
                continue
            failure = None
            if row.primary_failure:
                try:
                    failure = FailureClass(row.primary_failure)
                except ValueError:
                    failure = None
            out.append(
                Observation(
                    x_unit=tuple(row.x_unit),
                    robustness=row.robustness,
                    verdict=Verdict(row.verdict) if row.verdict else Verdict.PASS,
                    failure_class=failure,
                    run_id=row.id,
                )
            )
        return out

    def cancel_pending(self, campaign_id: UUID) -> int:
        result = execute(
            self._s,
            update(RunRow)
            .where(
                RunRow.campaign_id == campaign_id,
                RunRow.status == RunStatus.PENDING.value,
            )
            .values(status=RunStatus.CANCELLED.value),
        )
        return int(getattr(result, "rowcount", 0) or 0)
