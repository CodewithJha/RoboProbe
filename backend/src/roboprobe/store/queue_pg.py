"""PostgreSQL run queue: SKIP LOCKED claim and heartbeat reaper (docs/11 §4-§5).

Port lives in ``store.ports.RunQueue`` so this adapter does not import ``roboprobe.runner``.
Implements: T-012, FR-RUN-001, FR-RUN-002
"""

# ruff: noqa: D102, D107

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from roboprobe.core.errors import ConflictError, NotFoundError
from roboprobe.core.types import RunOutcome, RunStatus, Verdict
from roboprobe.store.engine import SessionFactory
from roboprobe.store.events import TOPIC_RUN_FINISHED, TOPIC_RUN_STARTED
from roboprobe.store.flush import execute
from roboprobe.store.mapping import run_record
from roboprobe.store.orm import RunRow
from roboprobe.store.records import ClaimedRun, OracleResultRecord, RunRecord
from roboprobe.store.repositories.events import SqlEventRepo
from roboprobe.store.repositories.oracle_results import SqlOracleResultRepo

__all__ = ["CLAIM_SQL", "REAP_SQL", "PostgresRunQueue"]

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

_CLAIMABLE_CAMPAIGN = """
(c.status='RUNNING' OR (c.status='COMPLETED' AND r.phase IN ('confirm', 'replay', 'manual')))
"""

CLAIM_SQL = f"""
UPDATE runs SET status='CLAIMED', worker_id=:worker, claimed_at=now(), attempt=attempt+1
WHERE id = (
  SELECT r.id FROM runs r JOIN campaigns c ON c.id = r.campaign_id
  WHERE r.status='PENDING' AND r.backend=:backend AND {_CLAIMABLE_CAMPAIGN}
  ORDER BY r.priority, r.enqueued_at
  FOR UPDATE OF r SKIP LOCKED
  LIMIT 1)
RETURNING id, campaign_id, scenario_hash, scenario_values, seed, attempt, backend, ordinal, phase,
          (SELECT source.verdict FROM runs source WHERE source.id = runs.replay_of)
          AS source_verdict
"""  # noqa: S608 - fixed claim predicate, bound request parameters

_DEPTH_SQL = f"""
SELECT count(*) FROM runs r JOIN campaigns c ON c.id = r.campaign_id
WHERE r.status='PENDING' AND r.backend=:backend AND {_CLAIMABLE_CAMPAIGN}
"""  # noqa: S608 - fixed claim predicate, bound request parameters

REAP_SQL = """
UPDATE runs r SET status = CASE WHEN r.attempt < :max_attempts THEN 'PENDING' ELSE 'ERROR' END,
                  verdict = CASE WHEN r.attempt < :max_attempts THEN NULL ELSE 'INVALID' END,
                  worker_id = NULL
FROM workers w
WHERE r.worker_id = w.id AND r.status IN ('CLAIMED','RUNNING')
  AND w.last_heartbeat < :now - make_interval(secs => :heartbeat_timeout_s)
RETURNING r.id, r.status, r.phase
"""


class PostgresRunQueue:
    """Implements: RunQueue."""

    def __init__(
        self,
        factory: SessionFactory,
        *,
        notify_channel: str,
        wall_timeout_s: float,
        sim_time_budget_s: float,
        on_confirmation_finished: Callable[[Session, RunRecord], None] | None = None,
    ) -> None:
        self._factory = factory
        self._notify_channel = notify_channel
        self._wall_timeout_s = wall_timeout_s
        self._sim_time_budget_s = sim_time_budget_s
        self._on_confirmation_finished = on_confirmation_finished

    def claim(self, worker_id: str, backend: str) -> ClaimedRun | None:
        session = self._factory()
        try:
            row = (
                execute(session, text(CLAIM_SQL), {"worker": worker_id, "backend": backend})
                .mappings()
                .first()
            )
            if row is None:
                session.commit()
                return None
            SqlEventRepo(session, self._notify_channel).append(
                TOPIC_RUN_STARTED,
                {
                    "run_id": str(row["id"]),
                    "campaign_id": str(row["campaign_id"]),
                    "ordinal": int(row["ordinal"]),
                    "worker_id": worker_id,
                },
                campaign_id=row["campaign_id"],
            )
            session.commit()
            values = row["scenario_values"]
            return ClaimedRun(
                run_id=row["id"],
                campaign_id=row["campaign_id"],
                scenario_hash=row["scenario_hash"],
                scenario_values=values if isinstance(values, dict) else {},
                seed=int(row["seed"]),
                attempt=int(row["attempt"]),
                backend=row["backend"],
                ordinal=int(row["ordinal"]),
                worker_id=worker_id,
                wall_timeout_s=self._wall_timeout_s,
                sim_time_budget_s=self._sim_time_budget_s,
                phase=row["phase"],
                source_verdict=row["source_verdict"],
            )
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def mark_running(self, run_id: UUID) -> None:
        self._transition(run_id, RunStatus.CLAIMED, RunStatus.RUNNING, started=True)

    def mark_evaluating(self, run_id: UUID) -> None:
        self._transition(run_id, RunStatus.RUNNING, RunStatus.EVALUATING)

    def complete(
        self, run_id: UUID, outcome: RunOutcome, *, manifest: dict[str, object] | None = None
    ) -> None:
        session = self._factory()
        try:
            run = self._require(session, run_id)
            self._check(RunStatus(run.status), RunStatus.DONE)
            run.status = RunStatus.DONE.value
            run.verdict = outcome.verdict.value
            run.robustness = outcome.robustness
            run.primary_failure = (
                None if outcome.primary_failure is None else outcome.primary_failure.value
            )
            run.metrics = dict(outcome.metrics)
            if manifest is not None:
                run.manifest = dict(manifest)
            run.finished_at = execute(session, text("SELECT now()")).scalar_one()
            SqlOracleResultRepo(session).replace_for_run(
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
            SqlEventRepo(session, self._notify_channel).append(
                TOPIC_RUN_FINISHED,
                {
                    "run_id": str(run_id),
                    "campaign_id": str(run.campaign_id),
                    "verdict": outcome.verdict.value,
                    "robustness": outcome.robustness,
                    "primary_failure": run.primary_failure,
                    "values": dict(run.scenario_values),
                },
                campaign_id=run.campaign_id,
            )
            self._finish_confirmation(session, run)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def fail(self, run_id: UUID, infra_error: str) -> None:
        session = self._factory()
        try:
            run = self._require(session, run_id)
            self._check(RunStatus(run.status), RunStatus.ERROR)
            run.status = RunStatus.ERROR.value
            run.verdict = Verdict.INVALID.value
            run.infra_error = infra_error
            run.robustness = None
            run.finished_at = execute(session, text("SELECT now()")).scalar_one()
            SqlEventRepo(session, self._notify_channel).append(
                TOPIC_RUN_FINISHED,
                {
                    "run_id": str(run_id),
                    "campaign_id": str(run.campaign_id),
                    "verdict": Verdict.INVALID.value,
                    "robustness": None,
                    "primary_failure": None,
                    "values": dict(run.scenario_values),
                },
                campaign_id=run.campaign_id,
            )
            self._finish_confirmation(session, run)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def reap(self, now: datetime, heartbeat_timeout_s: float, max_attempts: int) -> int:
        session = self._factory()
        try:
            rows = (
                execute(
                    session,
                    text(REAP_SQL),
                    {
                        "now": now,
                        "heartbeat_timeout_s": heartbeat_timeout_s,
                        "max_attempts": max_attempts,
                    },
                )
                .mappings()
                .all()
            )
            if self._on_confirmation_finished is not None:
                for row in rows:
                    if row["phase"] == "confirm" and row["status"] == RunStatus.ERROR:
                        self._finish_confirmation(session, self._require(session, row["id"]))
            session.commit()
            return len(rows)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def depth(self, backend: str) -> int:
        session = self._factory()
        try:
            count = execute(
                session,
                text(_DEPTH_SQL),
                {"backend": backend},
            ).scalar_one()
            return int(count)
        finally:
            session.close()

    def _finish_confirmation(self, session: Session, run: RunRow) -> None:
        if run.phase == "confirm" and self._on_confirmation_finished is not None:
            session.flush()
            self._on_confirmation_finished(session, run_record(run))

    def _require(self, session: Session, run_id: UUID) -> RunRow:
        run = session.get(RunRow, run_id)
        if run is None:
            msg = "run not found"
            raise NotFoundError(msg, context={"run_id": str(run_id)})
        return run

    def _transition(
        self, run_id: UUID, expected: RunStatus, target: RunStatus, *, started: bool = False
    ) -> None:
        session = self._factory()
        try:
            run = self._require(session, run_id)
            current = RunStatus(run.status)
            if current != expected:
                self._check(current, target)
            run.status = target.value
            if started:
                run.started_at = execute(session, text("SELECT now()")).scalar_one()
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _check(current: RunStatus, target: RunStatus) -> None:
        if target not in _LEGAL[current]:
            msg = "illegal run status transition"
            raise ConflictError(msg, context={"from": current.value, "to": target.value})
