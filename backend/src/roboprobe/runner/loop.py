"""CampaignLoop.step: propose → enqueue runs.

Implements: T-041a, FR-RUN-001, FR-RUN-005, FR-SEL-006, FR-SEL-007
"""

from __future__ import annotations

import importlib
import threading
from collections.abc import Callable, Sequence
from typing import Any, Final
from uuid import UUID

import numpy as np
import structlog

from roboprobe.core.clock import Clock
from roboprobe.core.metrics_registry import Metrics, create_metrics
from roboprobe.core.seeding import RUN, derive_seed
from roboprobe.core.settings.runner import RunnerSettings
from roboprobe.core.settings.selection import SelectionDefaults
from roboprobe.core.types import (
    CampaignStatus,
    JsonValue,
    Observation,
    Proposal,
    RunStatus,
)
from roboprobe.observability.tracing import span
from roboprobe.runner.ports import CampaignView, UowFactory
from roboprobe.runner.scheduler import Scheduler
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.selection.base import Strategy, StrategyContext
from roboprobe.selection.baselines.sobol import SobolStrategy

__all__ = ["CampaignLoop"]

log = structlog.get_logger(__name__)

_INFLIGHT: Final = frozenset(
    {RunStatus.PENDING, RunStatus.CLAIMED, RunStatus.RUNNING, RunStatus.EVALUATING}
)


class CampaignLoop:
    """One scheduling tick for a campaign (docs/05 §5.1)."""

    def __init__(  # noqa: PLR0913 - loop wiring matches docs/05 §5.1
        self,
        campaign_id: UUID,
        *,
        uow_factory: UowFactory,
        settings: RunnerSettings,
        selection: SelectionDefaults,
        space: ScenarioSpace,
        strategy: Strategy,
        scheduler: Scheduler,
        clock: Clock,
        metrics: Metrics | None = None,
        new_run_factory: Callable[..., object] | None = None,
        strategy_state_factory: Callable[..., object] | None = None,
        on_checkpoint: Callable[[Strategy, int], None] | None = None,
    ) -> None:
        """Wire campaign id, UoW, strategy, scheduler, clock and optional factories."""
        self._campaign_id = campaign_id
        self._uow_factory = uow_factory
        self._settings = settings
        self._selection = selection
        self._space = space
        self._strategy = strategy
        self._scheduler = scheduler
        self._clock = clock
        self._metrics = metrics if metrics is not None else create_metrics(enabled=False)
        self._new_run_factory = new_run_factory or _default_new_run
        self._strategy_state_factory = strategy_state_factory or _default_strategy_state
        self._on_checkpoint = on_checkpoint
        self._consecutive_fallbacks = 0

    @property
    def consecutive_fallbacks(self) -> int:
        """How many propose timeouts in a row (for GP_FALLBACK_REPEATED alerts)."""
        return self._consecutive_fallbacks

    def step(self) -> int:
        """One scheduling tick; returns the number of run rows inserted (attempted)."""
        with self._uow_factory() as uow:
            campaign = uow.campaigns.get(self._campaign_id)
            if campaign is None or campaign.status is not CampaignStatus.RUNNING:
                return 0
            snapshot = uow.runs.scheduling_snapshot(
                self._campaign_id,
                inflight_statuses=_INFLIGHT,
                count_invalid=self._settings.count_invalid_in_budget,
            )
            workers = uow.workers.online(campaign.backend)
            target = self._scheduler.target_inflight(len(workers), campaign.batch_size)
            free = target - len(snapshot.inflight_vectors)
            if free <= 0:
                return 0
            budget_left = campaign.budget - snapshot.budget_used
            if budget_left <= 0:
                return 0
            q = min(free, budget_left, self._settings.max_batch_size)
            history = uow.runs.history(self._campaign_id)
            pending_unit = [
                np.asarray(point, dtype=np.float64) for point in snapshot.inflight_vectors
            ]
            proposals, used_fallback = self._propose(history, pending_unit, q)
            if used_fallback:
                self._consecutive_fallbacks += 1
            else:
                self._consecutive_fallbacks = 0
            if not proposals:
                return 0
            new_runs = self._build_runs(campaign, proposals, snapshot.next_ordinal)
            ids = uow.runs.insert_batch(new_runs)
            state = self._strategy.state_dict()
            uow.strategy_states.upsert(
                self._strategy_state_factory(self._campaign_id, len(history), _jsonable(state))
            )
            uow.commit()
        if self._on_checkpoint is not None:
            self._on_checkpoint(self._strategy, len(history))
        log.info(
            "strategy.proposed",
            campaign_id=str(self._campaign_id),
            n=len(proposals),
            strategy=self._strategy.id,
        )
        return len(ids)

    def _propose(
        self,
        history: Sequence[Observation],
        pending: Sequence[np.ndarray],
        q: int,
    ) -> tuple[list[Proposal], bool]:
        started = self._clock.monotonic()
        box: list[list[Proposal] | BaseException] = []

        def _call() -> None:
            try:
                with span("strategy.propose"):
                    box.append(self._strategy.propose(history, pending, q))
            except BaseException as exc:
                box.append(exc)

        thread = threading.Thread(target=_call, name="propose", daemon=True)
        thread.start()
        thread.join(self._selection.propose_timeout_s)
        elapsed = self._clock.monotonic() - started
        self._metrics.selector_propose_seconds.labels(strategy=self._strategy.id).observe(elapsed)
        if thread.is_alive() or not box:
            log.info(
                "selector.fallback",
                campaign_id=str(self._campaign_id),
                strategy=self._strategy.id,
                reason="timeout",
            )
            return self._sobol_fallback(history, pending, q), True
        result = box[0]
        if isinstance(result, BaseException):
            log.info(
                "selector.fallback",
                campaign_id=str(self._campaign_id),
                strategy=self._strategy.id,
                reason=type(result).__name__,
            )
            return self._sobol_fallback(history, pending, q), True
        return result, False

    def _sobol_fallback(
        self,
        history: Sequence[Observation],
        pending: Sequence[np.ndarray],
        q: int,
    ) -> list[Proposal]:
        ctx = StrategyContext(
            space=self._space,
            budget=self._strategy.ctx.budget,
            seed=self._strategy.ctx.seed,
            batch_size=self._strategy.ctx.batch_size,
            params=dict(self._strategy.ctx.params),
            selection=self._strategy.ctx.selection,
            scenario=self._strategy.ctx.scenario,
        )
        return SobolStrategy(ctx).propose(history, pending, q)

    def _build_runs(
        self, campaign: CampaignView, proposals: Sequence[Proposal], next_ordinal: int
    ) -> list[object]:
        rows: list[object] = []
        ordinal = next_ordinal
        for proposal in proposals:
            values = dict(proposal.scenario.values)
            # Pins already reflected in the strategy space; keep campaign pins in values.
            for key, value in campaign.pins.items():
                if key not in values:
                    values[key] = value  # type: ignore[assignment]
            x_unit = tuple(float(x) for x in self._space.to_unit(values))
            rationale: dict[str, JsonValue] = {
                "strategy": proposal.strategy,
                "phase": proposal.phase,
                "acquisition_value": proposal.acquisition_value,
                "tags": list(proposal.tags),
            }
            if proposal.predicted_mean is not None:
                rationale["predicted_mean"] = proposal.predicted_mean
            if proposal.predicted_std is not None:
                rationale["predicted_std"] = proposal.predicted_std
            for repeat_index in range(max(1, campaign.repeats)):
                seed = derive_seed(campaign.seed, RUN, ordinal, repeat_index)
                rows.append(
                    self._new_run_factory(
                        campaign_id=self._campaign_id,
                        ordinal=ordinal,
                        repeat_index=repeat_index,
                        backend=campaign.backend,
                        scenario_hash=proposal.scenario.scenario_hash,
                        scenario_values=values,
                        x_unit=x_unit,
                        seed=seed,
                        phase=str(proposal.phase),
                        proposal=rationale,
                    )
                )
            ordinal += 1
        return rows


def _jsonable(state: dict[str, Any]) -> dict[str, JsonValue]:
    out: dict[str, JsonValue] = {}
    for key, value in state.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
        elif isinstance(value, dict):
            out[key] = _jsonable(value)
        elif isinstance(value, (list, tuple)):
            out[key] = list(value)
        else:
            out[key] = str(value)
    return out


def _default_new_run(**kwargs: object) -> object:
    return importlib.import_module("roboprobe.store.records").NewRun(**kwargs)


def _default_strategy_state(campaign_id: UUID, n_obs: int, state: dict[str, JsonValue]) -> object:
    return importlib.import_module("roboprobe.store.records").StrategyStateRecord(
        campaign_id=campaign_id, n_obs=n_obs, state=state
    )
