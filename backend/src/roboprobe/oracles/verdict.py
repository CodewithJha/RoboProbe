"""VerdictEngine: INVALID / FAIL / PASS and rho = min failure robustness (docs/08 §5).

Implements: FR-ORC-003, FR-ORC-004, FR-ORC-006
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from roboprobe.core.settings import OracleThresholds
from roboprobe.core.types import FailureClass, RunOutcome, TaskSpec, Trace, Verdict
from roboprobe.oracles.base import Oracle
from roboprobe.oracles.infra import InfraCheck
from roboprobe.oracles.metrics import compute_run_metrics

__all__ = ["PRIMARY_TIE_BREAK", "EpisodeView", "VerdictEngine"]

# docs/08 §5: COL > INST > LOC > PLAN > STUCK > TIMEOUT
PRIMARY_TIE_BREAK: tuple[FailureClass, ...] = (
    FailureClass.COL,
    FailureClass.INST,
    FailureClass.LOC,
    FailureClass.PLAN,
    FailureClass.STUCK,
    FailureClass.TIMEOUT,
)
_TIE_RANK = {cls: i for i, cls in enumerate(PRIMARY_TIE_BREAK)}


class EpisodeView(Protocol):
    """Minimal episode surface (``EpisodeResult`` once backends ship)."""

    trace: Trace
    infra_error: str | None


class VerdictEngine:
    """Combine InfraCheck + oracles into a :class:`RunOutcome`."""

    def __init__(
        self,
        oracles: Sequence[Oracle],
        *,
        infra: InfraCheck | None = None,
    ) -> None:
        """``oracles`` are evaluated only when InfraCheck passes."""
        self._oracles = tuple(oracles)
        self._infra = infra or InfraCheck(oracles[0].thresholds if oracles else OracleThresholds())

    def judge(self, result: EpisodeView, task: TaskSpec) -> RunOutcome:
        """INVALID if infra fails; else FAIL iff min failure-oracle r < 0."""
        metrics = compute_run_metrics(result.trace, task, thresholds=self._infra.thresholds)
        infra_res = self._infra.evaluate(result.trace, task, infra_error=result.infra_error)
        if infra_res is not None:
            return RunOutcome(
                verdict=Verdict.INVALID,
                robustness=None,
                primary_failure=FailureClass.INFRA,
                oracle_results=(infra_res,),
                metrics=metrics,
            )
        results = tuple(o.evaluate(result.trace, task) for o in self._oracles)
        failures = [r for r in results if r.severity == "failure"]
        rho = min(r.robustness for r in failures) if failures else 1.0
        violated = [r for r in failures if r.violated]
        if not violated:
            return RunOutcome(
                verdict=Verdict.PASS,
                robustness=rho,
                primary_failure=None,
                oracle_results=results,
                metrics=metrics,
            )
        primary = min(
            violated,
            key=lambda r: (
                r.first_violation_t if r.first_violation_t is not None else float("inf"),
                _TIE_RANK.get(r.failure_class, len(_TIE_RANK)),
            ),
        )
        return RunOutcome(
            verdict=Verdict.FAIL,
            robustness=rho,
            primary_failure=primary.failure_class,
            oracle_results=results,
            metrics=metrics,
        )
