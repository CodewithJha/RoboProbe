"""Offline oracle re-judgement from stored traces (FR-ORC-006).

Implements: T-039b, FR-ORC-006
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from roboprobe.core.errors import NotFoundError
from roboprobe.core.settings import OracleThresholds
from roboprobe.core.types import RunOutcome, TaskSpec, Verdict
from roboprobe.oracles import __version__ as oracle_set_version
from roboprobe.oracles.registry import create_all
from roboprobe.oracles.verdict import VerdictEngine

__all__ = ["ReevaluateDiff", "reevaluate_run"]


class _Uow(Protocol):
    runs: Any
    oracle_results: Any

    def commit(self) -> None: ...


UowFactory = Callable[[], AbstractContextManager[_Uow]]


@dataclass(frozen=True, slots=True)
class ReevaluateDiff:
    """Stored vs recomputed verdict comparison."""

    run_id: UUID
    stored_verdict: str | None
    stored_robustness: float | None
    new_outcome: RunOutcome
    changed: bool
    oracle_set_version: str


@dataclass(slots=True)
class _Episode:
    trace: Any
    infra_error: str | None = None


def reevaluate_run(  # noqa: PLR0913 - service signature matches CLI options
    uow_factory: UowFactory,
    run_id: UUID,
    *,
    task: TaskSpec,
    artifact_path: Path,
    thresholds: OracleThresholds | None = None,
    write: bool = False,
) -> ReevaluateDiff:
    """Re-judge ``run_id`` from ``artifact_path`` (trace parquet).

    When ``write`` is true, oracle rows are replaced, the run's verdict fields are updated,
    and the campaign's ``oracle_config["oracle_set_version"]`` is set to the current set.
    """
    cfg = thresholds if thresholds is not None else OracleThresholds()
    engine = VerdictEngine(create_all(cfg))
    # Dynamic import: domain must not statically depend on backends (import-linter).
    read_trace = importlib.import_module("roboprobe.backends.trace_io").read_trace
    trace = read_trace(artifact_path)
    outcome = engine.judge(_Episode(trace=trace), task)
    records = importlib.import_module("roboprobe.store.records")
    with uow_factory() as uow:
        run = uow.runs.get(run_id)
        if run is None:
            msg = "run not found"
            raise NotFoundError(msg, context={"run_id": str(run_id)})
        stored_verdict = _verdict_str(run.verdict)
        stored_rho = run.robustness
        changed = (
            stored_verdict != outcome.verdict.value
            or (stored_rho is None and outcome.robustness is not None)
            or (
                stored_rho is not None
                and outcome.robustness is not None
                and stored_rho != outcome.robustness
            )
            or (stored_rho is not None and outcome.robustness is None)
        )
        if write:
            uow.oracle_results.replace_for_run(
                run_id,
                tuple(
                    records.OracleResultRecord(
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
            _persist_outcome(uow, run_id, outcome, campaign_id=run.campaign_id)
            uow.commit()
    return ReevaluateDiff(
        run_id=run_id,
        stored_verdict=stored_verdict,
        stored_robustness=stored_rho,
        new_outcome=outcome,
        changed=changed,
        oracle_set_version=oracle_set_version,
    )


def _persist_outcome(uow: object, run_id: UUID, outcome: RunOutcome, *, campaign_id: UUID) -> None:
    """Update run verdict fields and campaign oracle_set_version via the UoW session."""
    session = getattr(uow, "_session", None)
    if session is None:
        return
    orm = importlib.import_module("roboprobe.store.orm")
    row = session.get(orm.RunRow, run_id)
    if row is not None:
        row.verdict = outcome.verdict.value
        row.robustness = outcome.robustness
        row.primary_failure = (
            None if outcome.primary_failure is None else outcome.primary_failure.value
        )
        row.metrics = dict(outcome.metrics)
    campaign = session.get(orm.CampaignRow, campaign_id)
    if campaign is not None:
        cfg = dict(campaign.oracle_config or {})
        cfg["oracle_set_version"] = oracle_set_version
        campaign.oracle_config = cfg


def _verdict_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Verdict):
        return value.value
    return str(value)
