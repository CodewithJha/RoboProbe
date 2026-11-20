"""Run repository."""

# ruff: noqa: D102, D107

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from roboprobe.core.types import FailureClass, Observation, Verdict
from roboprobe.store.ids import new_uuid
from roboprobe.store.mapping import run_record
from roboprobe.store.orm import RunRow
from roboprobe.store.pagination import Page, clamp_limit, extra_item
from roboprobe.store.records import NewRun, RunRecord


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
        self._s.execute(stmt)
        return tuple(ids)

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

    def history(self, campaign_id: UUID) -> list[Observation]:
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
