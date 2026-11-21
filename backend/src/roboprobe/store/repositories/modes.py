"""Failure-mode repository."""

# ruff: noqa: D102, D107

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from roboprobe.core.errors import NotFoundError
from roboprobe.store.flush import execute
from roboprobe.store.mapping import mode_record
from roboprobe.store.orm import FailureModeMemberRow, FailureModeRow
from roboprobe.store.records import FailureModeMemberRecord, FailureModeRecord


class SqlFailureModeRepo:
    """Implements: FailureModeRepo."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, mode_id: UUID) -> FailureModeRecord | None:
        row = self._s.get(FailureModeRow, mode_id)
        return None if row is None else mode_record(row)

    def patch(
        self,
        mode_id: UUID,
        *,
        label: str | None = None,
        status: str | None = None,
    ) -> None:
        values: dict[str, object] = {}
        if label is not None:
            values["label"] = label
            values["label_is_user"] = True
        if status is not None:
            values["status"] = status
        if not values:
            return
        result = execute(
            self._s, update(FailureModeRow).where(FailureModeRow.id == mode_id).values(**values)
        )
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            msg = "failure mode not found"
            raise NotFoundError(msg, context={"mode_id": str(mode_id)})

    def list_for_campaign(self, campaign_id: UUID) -> tuple[FailureModeRecord, ...]:
        rows = self._s.scalars(
            select(FailureModeRow)
            .where(FailureModeRow.campaign_id == campaign_id)
            .order_by(FailureModeRow.code)
        ).all()
        return tuple(mode_record(r) for r in rows)

    def upsert_modes(
        self,
        campaign_id: UUID,
        modes: Sequence[FailureModeRecord],
        members: Sequence[FailureModeMemberRecord],
    ) -> None:
        existing = {
            row.code: row
            for row in self._s.scalars(
                select(FailureModeRow).where(FailureModeRow.campaign_id == campaign_id)
            )
        }
        kept_ids: list[UUID] = []
        for mode in modes:
            row = existing.get(mode.code)
            if row is None:
                mode_id = mode.id
                self._s.add(
                    FailureModeRow(
                        id=mode_id,
                        campaign_id=campaign_id,
                        code=mode.code,
                        label=mode.label,
                        label_is_user=mode.label_is_user,
                        primary_class=mode.primary_class,
                        class_mix=dict(mode.class_mix),
                        size=mode.size,
                        param_ranges=dict(mode.param_ranges),
                        characteristic=list(mode.characteristic),
                        medoid_run_id=mode.medoid_run_id,
                        minimal_run_id=mode.minimal_run_id,
                        rules=list(mode.rules),
                        interaction=None if mode.interaction is None else dict(mode.interaction),
                        reproducibility=mode.reproducibility,
                        status=mode.status,
                        first_seen_run=mode.first_seen_run,
                        analysis_id=mode.analysis_id,
                    )
                )
                kept_ids.append(mode_id)
                continue
            kept_ids.append(row.id)
            label = row.label if row.label_is_user else mode.label
            row.primary_class = mode.primary_class
            row.class_mix = dict(mode.class_mix)
            row.size = mode.size
            row.param_ranges = dict(mode.param_ranges)
            row.characteristic = list(mode.characteristic)
            row.medoid_run_id = mode.medoid_run_id
            row.minimal_run_id = mode.minimal_run_id
            row.rules = list(mode.rules)
            row.interaction = None if mode.interaction is None else dict(mode.interaction)
            row.reproducibility = mode.reproducibility
            row.status = mode.status
            row.first_seen_run = mode.first_seen_run
            row.analysis_id = mode.analysis_id
            row.label = label
        self._s.flush()
        if kept_ids:
            execute(
                self._s,
                delete(FailureModeMemberRow).where(FailureModeMemberRow.mode_id.in_(kept_ids)),
            )
        code_to_id = {
            row.code: row.id
            for row in self._s.scalars(
                select(FailureModeRow).where(FailureModeRow.campaign_id == campaign_id)
            )
        }
        for member in members:
            mode_id = member.mode_id
            if mode_id not in set(code_to_id.values()):
                continue
            stmt = insert(FailureModeMemberRow).values(
                mode_id=mode_id, run_id=member.run_id, membership=member.membership
            )
            execute(self._s, stmt)
