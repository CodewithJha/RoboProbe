"""Orchestrator composition root: settings → adapters → supervisor deps.

The long-running :class:`~roboprobe.runner.orchestrator.Orchestrator` (T-048) is constructed
from :class:`OrchestratorServices`.

Layer: Application (L3) — composition root.

Implements: T-046, NFR-EXT-001, NFR-EXT-002
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from roboprobe.bootstrap._infra import Infrastructure, build_infrastructure
from roboprobe.core.clock import Clock, SystemClock
from roboprobe.core.metrics_registry import Metrics, create_metrics
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.runner.lifecycle import CampaignService
from roboprobe.runner.ports import RunQueuePort, UnitOfWorkPort
from roboprobe.runner.reaper import Reaper
from roboprobe.runner.scheduler import Scheduler

__all__ = ["OrchestratorServices", "build_orchestrator"]


@dataclass(frozen=True, slots=True)
class OrchestratorServices:
    """Injected collaborators for the orchestrator supervisor (docs/05 §5.1)."""

    settings: RoboProbeSettings
    infra: Infrastructure
    clock: Clock
    metrics: Metrics
    campaigns: CampaignService
    reaper: Reaper
    scheduler: Scheduler

    @property
    def uow_factory(self) -> Callable[[], UnitOfWorkPort]:
        """Unit-of-work factory bound to the process engine."""
        return cast("Callable[[], UnitOfWorkPort]", self.infra.uow_factory)

    def close(self) -> None:
        """Dispose pooled DB connections."""
        self.infra.close()


def build_orchestrator(settings: RoboProbeSettings) -> OrchestratorServices:
    """Wire orchestrator dependencies from ``settings``."""
    infra = build_infrastructure(settings)
    clock = SystemClock()
    metrics = create_metrics(enabled=settings.observability.metrics_enabled)
    uow_factory = cast("Callable[[], UnitOfWorkPort]", infra.uow_factory)
    reaper = Reaper(
        uow_factory=uow_factory,
        queue=cast("RunQueuePort", infra.queue),
        settings=settings.runner,
        clock=clock,
    )
    return OrchestratorServices(
        settings=settings,
        infra=infra,
        clock=clock,
        metrics=metrics,
        campaigns=CampaignService(uow_factory),
        reaper=reaper,
        scheduler=Scheduler(settings.runner),
    )
