"""In-memory UnitOfWork, repositories and RunQueue (docs/18 §4.3, T-015).

Fakes implement the same ports as the SQLAlchemy adapters and are the default
backend for runner/API unit tests (no Postgres). Thread-safe where the queue is shared.
"""

# ruff: noqa: TRY003, D105, D107

from __future__ import annotations

import copy
import threading
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from types import TracebackType
from typing import Any
from uuid import UUID

from roboprobe.core.errors import ConflictError, NotFoundError, ValidationError
from roboprobe.core.types import (
    CampaignStatus,
    FailureClass,
    JsonValue,
    Observation,
    RunOutcome,
    RunStatus,
    Verdict,
)
from roboprobe.store.ids import new_uuid
from roboprobe.store.pagination import Page, clamp_limit, extra_item
from roboprobe.store.records import (
    AnalysisRecord,
    ArtifactRecord,
    CampaignRecord,
    ClaimedRun,
    EventRecord,
    ExperimentRecord,
    FailureModeMemberRecord,
    FailureModeRecord,
    NewRun,
    OracleResultRecord,
    RiskMapRecord,
    RunRecord,
    SpaceRecord,
    StrategyStateRecord,
    SutProfileRecord,
    WorkerRecord,
)

__all__ = ["InMemoryRunQueue", "InMemoryUnitOfWork"]

_LEGAL: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.PENDING: frozenset({RunStatus.CLAIMED, RunStatus.CANCELLED}),
    RunStatus.CLAIMED: frozenset({RunStatus.RUNNING, RunStatus.PENDING, RunStatus.CANCELLED}),
    RunStatus.RUNNING: frozenset(
        {RunStatus.EVALUATING, RunStatus.PENDING, RunStatus.ERROR, RunStatus.CANCELLED}
    ),
    RunStatus.EVALUATING: frozenset({RunStatus.DONE, RunStatus.ERROR}),
    RunStatus.DONE: frozenset(),
    RunStatus.ERROR: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


class _Db:
    def __init__(self) -> None:
        self.spaces: dict[tuple[str, str], SpaceRecord] = {}
        self.suts: dict[str, SutProfileRecord] = {}
        self.campaigns: dict[UUID, CampaignRecord] = {}
        self.runs: dict[UUID, RunRecord] = {}
        self.oracles: dict[UUID, list[OracleResultRecord]] = {}
        self.strategies: dict[UUID, StrategyStateRecord] = {}
        self.modes: dict[UUID, FailureModeRecord] = {}
        self.members: list[FailureModeMemberRecord] = []
        self.risks: dict[UUID, RiskMapRecord] = {}
        self.analyses: dict[UUID, AnalysisRecord] = {}
        self.experiments: dict[UUID, ExperimentRecord] = {}
        self.workers: dict[str, WorkerRecord] = {}
        self.artifacts: dict[UUID, ArtifactRecord] = {}
        self.events: list[EventRecord] = []
        self.notify: list[tuple[str, str]] = []


class _Spaces:
    def __init__(self, db: _Db) -> None:
        self._db = db

    def get(self, space_id: str, version: str) -> SpaceRecord | None:
        return self._db.spaces.get((space_id, version))

    def add(self, record: SpaceRecord) -> None:
        self._db.spaces[(record.id, record.version)] = record

    def list(self, *, limit: int | None = None, cursor: str | None = None) -> Page[SpaceRecord]:
        size = clamp_limit(limit)
        rows = sorted(self._db.spaces.values(), key=lambda r: (r.id, r.version))
        if cursor:
            sid, _, ver = cursor.partition("\t")
            rows = [r for r in rows if (r.id, r.version) > (sid, ver)]
        items, extra = extra_item(rows, size)
        nxt = None if extra is None else f"{items[-1].id}\t{items[-1].version}"
        return Page(items=items, next_cursor=nxt)


class _Suts:
    def __init__(self, db: _Db) -> None:
        self._db = db

    def get(self, profile_id: str) -> SutProfileRecord | None:
        return self._db.suts.get(profile_id)

    def add(self, record: SutProfileRecord) -> None:
        self._db.suts[record.id] = record

    def list(
        self, *, limit: int | None = None, cursor: str | None = None
    ) -> Page[SutProfileRecord]:
        size = clamp_limit(limit)
        rows = sorted(self._db.suts.values(), key=lambda r: r.id)
        if cursor:
            rows = [r for r in rows if r.id > cursor]
        items, extra = extra_item(rows, size)
        nxt = None if extra is None else items[-1].id
        return Page(items=items, next_cursor=nxt)


class _Campaigns:
    def __init__(self, db: _Db) -> None:
        self._db = db

    def get(self, campaign_id: UUID) -> CampaignRecord | None:
        return self._db.campaigns.get(campaign_id)

    def add(self, record: CampaignRecord) -> None:
        self._db.campaigns[record.id] = record

    def set_status(
        self, campaign_id: UUID, status: CampaignStatus, *, reason: str | None = None
    ) -> None:
        rec = self._db.campaigns.get(campaign_id)
        if rec is None:
            raise NotFoundError("campaign not found", context={"campaign_id": str(campaign_id)})
        self._db.campaigns[campaign_id] = rec.model_copy(
            update={"status": status, "status_reason": reason}
        )

    def list(self, *, limit: int | None = None, cursor: str | None = None) -> Page[CampaignRecord]:
        size = clamp_limit(limit)
        rows = sorted(self._db.campaigns.values(), key=lambda r: r.id)
        if cursor:
            rows = [r for r in rows if str(r.id) > cursor]
        items, extra = extra_item(rows, size)
        nxt = None if extra is None else str(items[-1].id)
        return Page(items=items, next_cursor=nxt)

    def list_for_experiment(self, experiment_id: UUID) -> tuple[CampaignRecord, ...]:
        rows = sorted(
            (c for c in self._db.campaigns.values() if c.experiment_id == experiment_id),
            key=lambda c: c.id,
        )
        return tuple(rows)


class _Runs:
    def __init__(self, db: _Db) -> None:
        self._db = db

    def get(self, run_id: UUID) -> RunRecord | None:
        return self._db.runs.get(run_id)

    def insert_batch(self, runs: Sequence[NewRun]) -> tuple[UUID, ...]:
        ids: list[UUID] = []
        existing = {(r.campaign_id, r.ordinal, r.repeat_index) for r in self._db.runs.values()}
        for item in runs:
            key = (item.campaign_id, item.ordinal, item.repeat_index)
            run_id = item.id or new_uuid()
            ids.append(run_id)
            if key in existing:
                continue
            existing.add(key)
            self._db.runs[run_id] = RunRecord(
                id=run_id,
                campaign_id=item.campaign_id,
                ordinal=item.ordinal,
                repeat_index=item.repeat_index,
                backend=item.backend,
                scenario_hash=item.scenario_hash,
                scenario_values=item.scenario_values,
                x_unit=item.x_unit,
                seed=item.seed,
                phase=item.phase,
                proposal=item.proposal,
                tags=item.tags,
                replay_of=item.replay_of,
                status=RunStatus.PENDING,
                priority=item.priority,
                attempt=0,
                worker_id=None,
                verdict=None,
                robustness=None,
                primary_failure=None,
                warnings=(),
                metrics={},
                infra_error=None,
                manifest=None,
            )
        return tuple(ids)

    def import_many(self, runs: Sequence[RunRecord]) -> None:
        for item in runs:
            self._db.runs[item.id] = item

    def list_for_campaign(
        self, campaign_id: UUID, *, limit: int | None = None, cursor: str | None = None
    ) -> Page[RunRecord]:
        size = clamp_limit(limit)
        rows = sorted(
            (r for r in self._db.runs.values() if r.campaign_id == campaign_id),
            key=lambda r: r.id,
        )
        if cursor:
            rows = [r for r in rows if str(r.id) > cursor]
        items, extra = extra_item(rows, size)
        nxt = None if extra is None else str(items[-1].id)
        return Page(items=items, next_cursor=nxt)

    def history(
        self,
        campaign_id: UUID,
        *,
        exclude_phases: frozenset[str] | None = None,
    ) -> list[Observation]:
        skipped = frozenset({"confirm", "manual"}) if exclude_phases is None else exclude_phases
        rows = sorted(
            (
                r
                for r in self._db.runs.values()
                if r.campaign_id == campaign_id
                and r.status is RunStatus.DONE
                and r.verdict is not None
                and r.verdict is not Verdict.INVALID
                and r.phase not in skipped
            ),
            key=lambda r: (r.ordinal, r.repeat_index),
        )
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
                    x_unit=row.x_unit,
                    robustness=row.robustness,
                    verdict=row.verdict,
                    failure_class=failure,
                    run_id=row.id,
                )
            )
        return out

    def cancel_pending(self, campaign_id: UUID) -> int:
        n = 0
        for run_id, run in list(self._db.runs.items()):
            if run.campaign_id != campaign_id or run.status is not RunStatus.PENDING:
                continue
            self._db.runs[run_id] = run.model_copy(update={"status": RunStatus.CANCELLED})
            n += 1
        return n


class _Oracles:
    def __init__(self, db: _Db) -> None:
        self._db = db

    def replace_for_run(self, run_id: UUID, results: Sequence[OracleResultRecord]) -> None:
        self._db.oracles[run_id] = list(results)

    def list_for_run(self, run_id: UUID) -> tuple[OracleResultRecord, ...]:
        return tuple(self._db.oracles.get(run_id, ()))


class _Strategies:
    def __init__(self, db: _Db) -> None:
        self._db = db

    def get(self, campaign_id: UUID) -> StrategyStateRecord | None:
        return self._db.strategies.get(campaign_id)

    def upsert(self, record: StrategyStateRecord) -> None:
        self._db.strategies[record.campaign_id] = record


class _Modes:
    def __init__(self, db: _Db) -> None:
        self._db = db

    def get(self, mode_id: UUID) -> FailureModeRecord | None:
        return self._db.modes.get(mode_id)

    def list_for_campaign(self, campaign_id: UUID) -> tuple[FailureModeRecord, ...]:
        return tuple(
            sorted(
                (m for m in self._db.modes.values() if m.campaign_id == campaign_id),
                key=lambda m: m.code,
            )
        )

    def upsert_modes(
        self,
        campaign_id: UUID,
        modes: Sequence[FailureModeRecord],
        members: Sequence[FailureModeMemberRecord],
    ) -> None:
        by_code = {m.code: m for m in self._db.modes.values() if m.campaign_id == campaign_id}
        kept: set[UUID] = set()
        for mode in modes:
            prev = by_code.get(mode.code)
            if prev is None:
                self._db.modes[mode.id] = mode
                kept.add(mode.id)
                continue
            label = prev.label if prev.label_is_user else mode.label
            self._db.modes[prev.id] = mode.model_copy(
                update={"id": prev.id, "label": label, "label_is_user": prev.label_is_user}
            )
            kept.add(prev.id)
        self._db.members = [m for m in self._db.members if m.mode_id not in kept] + [
            m for m in members if m.mode_id in kept or m.mode_id in self._db.modes
        ]


class _Risks:
    def __init__(self, db: _Db) -> None:
        self._db = db

    def add(self, record: RiskMapRecord) -> None:
        self._db.risks[record.id] = record

    def latest(self, campaign_id: UUID) -> RiskMapRecord | None:
        rows = [r for r in self._db.risks.values() if r.campaign_id == campaign_id]
        if not rows:
            return None
        return sorted(rows, key=lambda r: r.created_at or datetime.min)[-1]


class _Analyses:
    def __init__(self, db: _Db) -> None:
        self._db = db

    def get(self, analysis_id: UUID) -> AnalysisRecord | None:
        return self._db.analyses.get(analysis_id)

    def add(self, record: AnalysisRecord) -> None:
        self._db.analyses[record.id] = record

    def list_for_campaign(self, campaign_id: UUID) -> tuple[AnalysisRecord, ...]:
        return tuple(m for m in self._db.analyses.values() if m.campaign_id == campaign_id)


class _Experiments:
    def __init__(self, db: _Db) -> None:
        self._db = db

    def get(self, experiment_id: UUID) -> ExperimentRecord | None:
        return self._db.experiments.get(experiment_id)

    def add(self, record: ExperimentRecord) -> None:
        self._db.experiments[record.id] = record

    def set_status(self, experiment_id: UUID, status: str) -> None:
        rec = self._db.experiments.get(experiment_id)
        if rec is None:
            raise NotFoundError(
                "experiment not found", context={"experiment_id": str(experiment_id)}
            )
        self._db.experiments[experiment_id] = rec.model_copy(update={"status": status})

    def set_results(self, experiment_id: UUID, results: dict[str, object]) -> None:
        rec = self._db.experiments.get(experiment_id)
        if rec is None:
            raise NotFoundError(
                "experiment not found", context={"experiment_id": str(experiment_id)}
            )
        self._db.experiments[experiment_id] = rec.model_copy(update={"results": dict(results)})

    def list(
        self, *, limit: int | None = None, cursor: str | None = None
    ) -> Page[ExperimentRecord]:
        size = clamp_limit(limit)
        rows = sorted(self._db.experiments.values(), key=lambda r: r.id)
        if cursor:
            rows = [r for r in rows if str(r.id) > cursor]
        items, extra = extra_item(rows, size)
        nxt = None if extra is None else str(items[-1].id)
        return Page(items=items, next_cursor=nxt)


class _Workers:
    def __init__(self, db: _Db) -> None:
        self._db = db

    def get(self, worker_id: str) -> WorkerRecord | None:
        return self._db.workers.get(worker_id)

    def register(self, record: WorkerRecord) -> None:
        self._db.workers[record.id] = record

    def heartbeat(self, worker_id: str, *, at: datetime) -> None:
        rec = self._db.workers.get(worker_id)
        if rec is None:
            raise NotFoundError("worker not found", context={"worker_id": worker_id})
        self._db.workers[worker_id] = rec.model_copy(update={"last_heartbeat": at})

    def set_status(
        self, worker_id: str, status: str, *, current_run_id: UUID | None = None
    ) -> None:
        rec = self._db.workers.get(worker_id)
        if rec is None:
            raise NotFoundError("worker not found", context={"worker_id": worker_id})
        self._db.workers[worker_id] = rec.model_copy(
            update={"status": status, "current_run_id": current_run_id}
        )

    def online(self, backend: str) -> tuple[WorkerRecord, ...]:
        return tuple(
            w
            for w in self._db.workers.values()
            if w.backend == backend and w.status in {"IDLE", "BUSY", "DRAINING"}
        )

    def stale(self, *, older_than: datetime) -> tuple[WorkerRecord, ...]:
        out: list[WorkerRecord] = []
        for worker in self._db.workers.values():
            if worker.status == "OFFLINE":
                continue
            if worker.last_heartbeat is None or worker.last_heartbeat < older_than:
                out.append(worker)
        return tuple(out)


class _Artifacts:
    def __init__(self, db: _Db) -> None:
        self._db = db

    def add(self, record: ArtifactRecord) -> None:
        self._db.artifacts[record.id] = record

    def get(self, artifact_id: UUID) -> ArtifactRecord | None:
        return self._db.artifacts.get(artifact_id)

    def list_for_run(self, run_id: UUID) -> tuple[ArtifactRecord, ...]:
        return tuple(a for a in self._db.artifacts.values() if a.run_id == run_id)

    def sha256_set(self) -> frozenset[str]:
        return frozenset(a.sha256 for a in self._db.artifacts.values())

    def delete(self, artifact_id: UUID) -> None:
        self._db.artifacts.pop(artifact_id, None)

    def bags_for_retention(self) -> tuple[ArtifactRecord, ...]:
        return tuple(a for a in self._db.artifacts.values() if a.kind == "bag")


class _Events:
    def __init__(self, db: _Db) -> None:
        self._db = db

    def append(
        self, topic: str, payload: Mapping[str, JsonValue], *, campaign_id: UUID | None = None
    ) -> int:
        event_id = (self._db.events[-1].id + 1) if self._db.events else 1
        self._db.events.append(
            EventRecord(id=event_id, topic=topic, campaign_id=campaign_id, payload=dict(payload))
        )
        self._db.notify.append(("roboprobe_events", str(event_id)))
        return event_id

    def since(
        self, last_id: int, *, campaign_id: UUID | None = None, limit: int | None = None
    ) -> tuple[EventRecord, ...]:
        size = clamp_limit(limit)
        rows = [e for e in self._db.events if e.id > last_id]
        if campaign_id is not None:
            rows = [e for e in rows if e.campaign_id == campaign_id]
        return tuple(rows[:size])


class InMemoryUnitOfWork:
    """In-memory UnitOfWork. Shared ``_Db`` is the committed state; each ``with`` copies it."""

    def __init__(self, db: _Db | None = None) -> None:
        self._committed = db or _Db()
        self._tx: _Db | None = None

    def __enter__(self) -> InMemoryUnitOfWork:
        self._tx = copy.deepcopy(self._committed)
        self._bind(self._tx)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()

    def commit(self) -> None:
        if self._tx is not None:
            self._committed = self._tx
            self._tx = copy.deepcopy(self._committed)
            self._bind(self._tx)

    def rollback(self) -> None:
        self._tx = copy.deepcopy(self._committed)
        self._bind(self._tx)

    def notify(self, channel: str, payload: str) -> None:
        db = self._require()
        db.notify.append((channel, payload))

    def _require(self) -> _Db:
        if self._tx is None:
            raise RuntimeError("UnitOfWork used outside a with-block")
        return self._tx

    def _bind(self, db: _Db) -> None:
        self.spaces = _Spaces(db)
        self.sut_profiles = _Suts(db)
        self.campaigns = _Campaigns(db)
        self.runs = _Runs(db)
        self.oracle_results = _Oracles(db)
        self.strategy_states = _Strategies(db)
        self.modes = _Modes(db)
        self.risk_maps = _Risks(db)
        self.analyses = _Analyses(db)
        self.experiments = _Experiments(db)
        self.workers = _Workers(db)
        self.artifacts = _Artifacts(db)
        self.events = _Events(db)


class InMemoryRunQueue:
    """Thread-safe in-memory queue with the same claim/reap semantics as Postgres."""

    def __init__(
        self, uow: InMemoryUnitOfWork, *, wall_timeout_s: float, sim_time_budget_s: float
    ) -> None:
        self._uow = uow
        self._lock = threading.Lock()
        self._wall = wall_timeout_s
        self._sim = sim_time_budget_s

    def claim(self, worker_id: str, backend: str) -> ClaimedRun | None:
        with self._lock, self._uow as uow:
            pending = [
                r
                for r in uow.runs._db.runs.values()
                if r.status is RunStatus.PENDING and r.backend == backend
            ]
            pending.sort(key=lambda r: (r.priority, str(r.id)))
            for run in pending:
                camp = uow.campaigns.get(run.campaign_id)
                if camp is None or camp.status is not CampaignStatus.RUNNING:
                    continue
                updated = run.model_copy(
                    update={
                        "status": RunStatus.CLAIMED,
                        "worker_id": worker_id,
                        "attempt": run.attempt + 1,
                    }
                )
                uow.runs._db.runs[run.id] = updated
                uow.events.append(
                    "run.started",
                    {
                        "run_id": str(run.id),
                        "campaign_id": str(run.campaign_id),
                        "ordinal": run.ordinal,
                        "worker_id": worker_id,
                    },
                    campaign_id=run.campaign_id,
                )
                uow.commit()
                return ClaimedRun(
                    run_id=run.id,
                    campaign_id=run.campaign_id,
                    scenario_hash=run.scenario_hash,
                    scenario_values=run.scenario_values,
                    seed=run.seed,
                    attempt=updated.attempt,
                    backend=run.backend,
                    ordinal=run.ordinal,
                    worker_id=worker_id,
                    wall_timeout_s=self._wall,
                    sim_time_budget_s=self._sim,
                )
            return None

    def mark_running(self, run_id: UUID) -> None:
        self._set(run_id, RunStatus.CLAIMED, RunStatus.RUNNING)

    def mark_evaluating(self, run_id: UUID) -> None:
        self._set(run_id, RunStatus.RUNNING, RunStatus.EVALUATING)

    def complete(
        self, run_id: UUID, outcome: RunOutcome, *, manifest: dict[str, object] | None = None
    ) -> None:
        with self._lock, self._uow as uow:
            run = self._need(uow, run_id)
            _check(run.status, RunStatus.DONE)
            updates: dict[str, object] = {
                "status": RunStatus.DONE,
                "verdict": outcome.verdict,
                "robustness": outcome.robustness,
                "primary_failure": None
                if outcome.primary_failure is None
                else outcome.primary_failure.value,
                "metrics": dict(outcome.metrics),
            }
            if manifest is not None:
                updates["manifest"] = dict(manifest)
            uow.runs._db.runs[run_id] = run.model_copy(update=updates)
            uow.oracle_results.replace_for_run(
                run_id,
                tuple(
                    OracleResultRecord(
                        run_id=run_id,
                        oracle_id=item.oracle_id,
                        failure_class=item.failure_class,
                        severity=item.severity,
                        violated=item.violated,
                        robustness=item.robustness,
                        first_violation_t=item.first_violation_t,
                        details=dict(item.details),
                    )
                    for item in outcome.oracle_results
                ),
            )
            uow.commit()

    def fail(self, run_id: UUID, infra_error: str) -> None:
        with self._lock, self._uow as uow:
            run = self._need(uow, run_id)
            _check(run.status, RunStatus.ERROR)
            uow.runs._db.runs[run_id] = run.model_copy(
                update={
                    "status": RunStatus.ERROR,
                    "verdict": Verdict.INVALID,
                    "infra_error": infra_error,
                    "robustness": None,
                }
            )
            uow.commit()

    def reap(self, now: datetime, heartbeat_timeout_s: float, max_attempts: int) -> int:
        cutoff = now - timedelta(seconds=heartbeat_timeout_s)
        n = 0
        with self._lock, self._uow as uow:
            for run in list(uow.runs._db.runs.values()):
                if (
                    run.status not in {RunStatus.CLAIMED, RunStatus.RUNNING}
                    or run.worker_id is None
                ):
                    continue
                worker = uow.workers.get(run.worker_id)
                if worker is None or worker.last_heartbeat is None:
                    continue
                if worker.last_heartbeat >= cutoff:
                    continue
                if run.attempt < max_attempts:
                    updated = run.model_copy(
                        update={"status": RunStatus.PENDING, "verdict": None, "worker_id": None}
                    )
                else:
                    updated = run.model_copy(
                        update={
                            "status": RunStatus.ERROR,
                            "verdict": Verdict.INVALID,
                            "worker_id": None,
                        }
                    )
                uow.runs._db.runs[run.id] = updated
                n += 1
            uow.commit()
        return n

    def depth(self, backend: str) -> int:
        with self._uow as uow:
            n = 0
            for run in uow.runs._db.runs.values():
                if run.status is not RunStatus.PENDING or run.backend != backend:
                    continue
                camp = uow.campaigns.get(run.campaign_id)
                if camp is not None and camp.status is CampaignStatus.RUNNING:
                    n += 1
            return n

    def _set(self, run_id: UUID, expected: RunStatus, target: RunStatus) -> None:
        with self._lock, self._uow as uow:
            run = self._need(uow, run_id)
            if run.status != expected:
                _check(run.status, target)
            uow.runs._db.runs[run_id] = run.model_copy(update={"status": target})
            uow.commit()

    @staticmethod
    def _need(uow: InMemoryUnitOfWork, run_id: UUID) -> RunRecord:
        run = uow.runs.get(run_id)
        if run is None:
            raise NotFoundError("run not found", context={"run_id": str(run_id)})
        return run


def _check(current: RunStatus, target: RunStatus) -> None:
    if target not in _LEGAL[current]:
        raise ConflictError(
            "illegal run status transition",
            context={"from": current.value, "to": target.value},
        )


# Silence unused import for ValidationError in this module (kept for contract parity).
_ = (Any, ValidationError)
