"""Enqueue and conclude confirmatory interaction runs (docs/09 §6).

Implements: T-074b, FR-ANA-005
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from typing import cast
from uuid import UUID

from roboprobe.analysis.interaction import InteractionTester
from roboprobe.analysis.types import (
    AnalysisRun,
    FailureModeSummary,
    InteractionVerdict,
    ParamRange,
)
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.core.settings.analysis import InteractionSettings
from roboprobe.core.types import FailureClass, JsonValue, ParamValue, Phase, RunStatus, Verdict
from roboprobe.runner.ports import FailureModeView, RunView, UnitOfWorkPort, UowFactory
from roboprobe.scenario.space import ScenarioSpace

__all__ = ["CONFIRM_PHASE", "CONFIRM_TAG", "ConfirmationService", "conclude_confirmation"]

CONFIRM_PHASE: Phase = "confirm"
CONFIRM_TAG = "confirm"
_PROPOSAL_SUBSET = "confirm_subset"
_PROPOSAL_MODE = "confirm_mode_id"
# Topic names mirrored from store.events (import-linter: runner must not import store).
_TOPIC_MODE_DISCOVERED = "mode.discovered"
_TOPIC_CAMPAIGN_UPDATED = "campaign.updated"


class ConfirmationService:
    """Plan, enqueue and conclude interaction confirmation runs for a mode."""

    def __init__(
        self,
        uow_factory: UowFactory,
        *,
        interaction: InteractionSettings,
        confirm_priority: int,
        load_space: Callable[[str, str], ScenarioSpace],
    ) -> None:
        """Wire UoW factory, interaction settings, queue priority and space loader."""
        self._uow_factory = uow_factory
        self._interaction = interaction
        self._priority = confirm_priority
        self._load_space = load_space

    def request(self, campaign_id: UUID, mode_id: UUID) -> list[UUID]:
        """Enqueue confirmatory runs for ``mode_id`` (idempotent while pending)."""
        records = importlib.import_module("roboprobe.store.records")
        with self._uow_factory() as uow:
            campaign = uow.campaigns.get(campaign_id)
            if campaign is None:
                msg = "campaign not found"
                raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
            mode = uow.modes.get(mode_id, for_update=True)
            if mode is None or mode.campaign_id != campaign_id:
                msg = "failure mode not found"
                raise NotFoundError(msg, context={"mode_id": str(mode_id)})
            existing = _pending_confirm_ids(uow, campaign_id, mode_id)
            if existing:
                return list(existing)
            if mode.interaction is not None:
                # Already concluded — return prior confirm run ids if any.
                done = _confirm_ids_for_mode(uow, campaign_id, mode_id)
                if done:
                    return list(done)
            space = self._load_space(campaign.space_id, campaign.space_version)
            summary = _summary_from_record(uow, mode)
            planned = InteractionTester(self._interaction, campaign.seed).plan(summary, space)
            if not planned:
                msg = "no confirmatory scenarios planned"
                raise ValidationError(msg, context={"mode_id": str(mode_id)})
            max_ordinal = _max_ordinal(uow, campaign_id)
            new_runs = []
            for index, item in enumerate(planned):
                scenario = item.scenario
                unit = space.to_unit(scenario.values)
                new_runs.append(
                    records.NewRun(
                        campaign_id=campaign_id,
                        ordinal=max_ordinal + 1 + index,
                        repeat_index=item.repeat,
                        backend=campaign.backend,
                        scenario_hash=scenario.scenario_hash,
                        scenario_values={str(k): _jsonable(v) for k, v in scenario.values.items()},
                        x_unit=tuple(float(v) for v in unit),
                        seed=item.seed,
                        phase=CONFIRM_PHASE,
                        proposal={
                            _PROPOSAL_MODE: str(mode_id),
                            _PROPOSAL_SUBSET: sorted(item.subset),
                        },
                        tags=tuple(item.tags),
                        priority=self._priority,
                    )
                )
            ids = list(uow.runs.insert_batch(new_runs))
            uow.commit()
        return ids

    def on_run_finished(self, run: RunView) -> None:
        """Conclude a mode for a run already persisted by an existing caller."""
        with self._uow_factory() as uow:
            conclude_confirmation(uow, run, interaction=self._interaction)
            uow.commit()

    def auto_confirm_top(self, campaign_id: UUID) -> list[UUID]:
        """Enqueue confirmation for the top-N modes when ``auto_confirm_top_n`` > 0."""
        n = self._interaction.auto_confirm_top_n
        if n <= 0:
            return []
        with self._uow_factory() as uow:
            modes = sorted(
                uow.modes.list_for_campaign(campaign_id),
                key=lambda m: (-m.size, m.code),
            )[:n]
            mode_ids = [m.id for m in modes]
        out: list[UUID] = []
        for mode_id in mode_ids:
            out.extend(self.request(campaign_id, mode_id))
        return out


_TERMINAL = frozenset(
    {RunStatus.DONE, RunStatus.ERROR, RunStatus.CANCELLED, "DONE", "ERROR", "CANCELLED"}
)


def _pending_confirm_ids(uow: UnitOfWorkPort, campaign_id: UUID, mode_id: UUID) -> tuple[UUID, ...]:
    ids: list[UUID] = []
    for run in _confirm_records_for_mode(uow, campaign_id, mode_id):
        status = run.status if isinstance(run.status, RunStatus) else RunStatus(str(run.status))
        if status not in {RunStatus.DONE, RunStatus.ERROR, RunStatus.CANCELLED}:
            ids.append(run.id)
    return tuple(ids)


def _confirm_ids_for_mode(
    uow: UnitOfWorkPort, campaign_id: UUID, mode_id: UUID
) -> tuple[UUID, ...]:
    return tuple(r.id for r in _confirm_records_for_mode(uow, campaign_id, mode_id))


def _confirm_records_for_mode(
    uow: UnitOfWorkPort, campaign_id: UUID, mode_id: UUID
) -> list[RunView]:
    out: list[RunView] = []
    cursor: str | None = None
    needle = str(mode_id)
    while True:
        page = uow.runs.list_for_campaign(campaign_id, cursor=cursor)
        for run in page.items:
            if run.phase != CONFIRM_PHASE:
                continue
            proposal = run.proposal or {}
            if str(proposal.get(_PROPOSAL_MODE, "")) == needle:
                out.append(run)
        cursor = page.next_cursor
        if cursor is None:
            break
    return out


def _max_ordinal(uow: UnitOfWorkPort, campaign_id: UUID) -> int:
    max_ord = -1
    cursor: str | None = None
    while True:
        page = uow.runs.list_for_campaign(campaign_id, cursor=cursor)
        for run in page.items:
            max_ord = max(max_ord, int(run.ordinal))
        cursor = page.next_cursor
        if cursor is None:
            break
    return max_ord


def _summary_from_record(uow: UnitOfWorkPort, mode: FailureModeView) -> FailureModeSummary:
    minimal = uow.runs.get(mode.minimal_run_id) if mode.minimal_run_id else None
    if minimal is None:
        msg = "mode minimal run missing"
        raise NotFoundError(msg, context={"mode_id": str(mode.id)})
    medoid = mode.medoid_run_id or mode.minimal_run_id
    ranges: dict[str, ParamRange] = {}
    for key, raw in (mode.param_ranges or {}).items():
        if isinstance(raw, Mapping):
            ranges[str(key)] = ParamRange(
                unit=str(raw.get("unit", "-")),
                q05=float(raw.get("q05", 0.0)),
                q95=float(raw.get("q95", 1.0)),
                space_coverage=float(raw.get("space_coverage", 0.0)),
            )
    try:
        primary = FailureClass(str(mode.primary_class))
    except ValueError:
        primary = FailureClass.COL
    class_mix: dict[FailureClass, float] = {}
    for key, value in (mode.class_mix or {}).items():
        try:
            class_mix[FailureClass(str(key))] = float(cast(float | int | str, value))
        except (TypeError, ValueError):
            continue
    return FailureModeSummary(
        code=mode.code,
        size=int(mode.size),
        primary_class=primary,
        class_mix=class_mix or {primary: 1.0},
        ranges=ranges,
        characteristic=frozenset(str(x) for x in mode.characteristic),
        medoid_run_id=medoid,
        minimal_run_id=mode.minimal_run_id,
        minimal_values=dict(minimal.scenario_values),
        member_run_ids=(),
        label=mode.label,
        provisional=False,
    )


def _to_analysis_run(run: RunView) -> AnalysisRun:
    proposal = run.proposal or {}
    raw_subset = proposal.get(_PROPOSAL_SUBSET)
    subset: frozenset[str] | None
    if isinstance(raw_subset, Sequence) and not isinstance(raw_subset, (str, bytes)):
        subset = frozenset(str(x) for x in raw_subset)
    else:
        subset = frozenset()
    verdict = run.verdict if isinstance(run.verdict, Verdict) else Verdict(str(run.verdict))
    primary = None
    if run.primary_failure:
        try:
            primary = FailureClass(str(run.primary_failure))
        except ValueError:
            primary = None
    phase: Phase = cast(Phase, run.phase if run.phase in _PHASES else CONFIRM_PHASE)
    return AnalysisRun(
        id=run.id,
        verdict=verdict,
        phase=phase,
        primary_failure=primary,
        values=dict(run.scenario_values),
        subset=subset,
    )


_PHASES = frozenset(
    {
        "warmup",
        "falsify",
        "mode_search",
        "boundary",
        "refine",
        "explore",
        "baseline",
        "manual",
        "confirm",
        "replay",
    }
)


def conclude_confirmation(
    uow: UnitOfWorkPort, run: RunView, *, interaction: InteractionSettings
) -> None:
    """Finalize a mode in the same transaction as its final run."""
    if run.phase != CONFIRM_PHASE:
        return
    raw_mode = (run.proposal or {}).get(_PROPOSAL_MODE)
    if raw_mode is None:
        return
    mode_id = UUID(str(raw_mode))
    campaign_id = run.campaign_id
    mode = uow.modes.get(mode_id, for_update=True)
    if mode is None or mode.campaign_id != campaign_id or mode.interaction is not None:
        return
    confirm_runs = _confirm_records_for_mode(uow, campaign_id, mode_id)
    if not confirm_runs or any(r.status not in _TERMINAL for r in confirm_runs):
        return
    campaign = uow.campaigns.get(campaign_id)
    if campaign is None:
        return
    summary = _summary_from_record(uow, mode)
    analysis_runs = [_to_analysis_run(r) for r in confirm_runs]
    verdict = InteractionTester(interaction, campaign.seed).conclude(summary, analysis_runs)
    _persist_verdict(uow, mode, verdict)
    uow.events.append(
        _TOPIC_MODE_DISCOVERED,
        {
            "campaign_id": str(campaign_id),
            "mode_id": str(mode_id),
            "code": mode.code,
            "interaction": verdict.status,
        },
        campaign_id=campaign_id,
    )
    uow.events.append(
        _TOPIC_CAMPAIGN_UPDATED,
        {
            "campaign_id": str(campaign_id),
            "status": campaign.status.value,
            "reason": "interaction_confirmed",
        },
        campaign_id=campaign_id,
    )


def _persist_verdict(
    uow: UnitOfWorkPort, mode: FailureModeView, verdict: InteractionVerdict
) -> None:
    payload: dict[str, JsonValue] = {
        "status": verdict.status,
        "order": verdict.order,
        "params": list(verdict.params),
        "ratios": {k: float(v) for k, v in verdict.ratios.items()},
        "evidence_run_ids": [str(i) for i in verdict.evidence_run_ids],
    }
    uow.modes.set_interaction(mode.id, payload)


def _jsonable(value: ParamValue | object) -> JsonValue:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return cast(JsonValue, value)
    return str(value)
