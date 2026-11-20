"""Worker repository."""

# ruff: noqa: D102, D107

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from roboprobe.core.errors import NotFoundError
from roboprobe.store.mapping import worker_record
from roboprobe.store.orm import WorkerRow
from roboprobe.store.records import WorkerRecord

_ONLINE = ("IDLE", "BUSY", "DRAINING")


class SqlWorkerRepo:
    """Implements: WorkerRepo."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, worker_id: str) -> WorkerRecord | None:
        row = self._s.get(WorkerRow, worker_id)
        return None if row is None else worker_record(row)

    def register(self, record: WorkerRecord) -> None:
        stmt = insert(WorkerRow).values(
            id=record.id,
            backend=record.backend,
            status=record.status,
            capabilities=dict(record.capabilities),
            version=record.version,
            current_run_id=record.current_run_id,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "backend": stmt.excluded.backend,
                "status": stmt.excluded.status,
                "capabilities": stmt.excluded.capabilities,
                "version": stmt.excluded.version,
                "current_run_id": stmt.excluded.current_run_id,
            },
        )
        self._s.execute(stmt)

    def heartbeat(self, worker_id: str, *, at: datetime) -> None:
        result = self._s.execute(
            update(WorkerRow).where(WorkerRow.id == worker_id).values(last_heartbeat=at)
        )
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            msg = "worker not found"
            raise NotFoundError(msg, context={"worker_id": worker_id})

    def set_status(
        self, worker_id: str, status: str, *, current_run_id: UUID | None = None
    ) -> None:
        result = self._s.execute(
            update(WorkerRow)
            .where(WorkerRow.id == worker_id)
            .values(status=status, current_run_id=current_run_id)
        )
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            msg = "worker not found"
            raise NotFoundError(msg, context={"worker_id": worker_id})

    def online(self, backend: str) -> tuple[WorkerRecord, ...]:
        rows = self._s.scalars(
            select(WorkerRow)
            .where(WorkerRow.backend == backend, WorkerRow.status.in_(_ONLINE))
            .order_by(WorkerRow.id)
        ).all()
        return tuple(worker_record(r) for r in rows)
