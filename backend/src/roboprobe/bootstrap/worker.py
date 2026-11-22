"""Worker composition root: settings → adapters → ``WorkerProcess``.

Layer: Application (L3) — composition root.

Implements: T-046, NFR-EXT-001, NFR-EXT-002, PR-19
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from roboprobe.backends.registry import get_backend
from roboprobe.bootstrap._infra import Infrastructure, build_infrastructure
from roboprobe.core.clock import SystemClock
from roboprobe.core.metrics_registry import create_metrics
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import TaskSpec
from roboprobe.oracles.registry import create_all
from roboprobe.oracles.verdict import VerdictEngine
from roboprobe.runner.ports import (
    ArtifactStorePort,
    RunQueuePort,
    SimulatorBackendPort,
    UnitOfWorkPort,
)
from roboprobe.runner.worker import WorkerProcess

__all__ = ["build_worker"]


def build_worker(
    settings: RoboProbeSettings,
    *,
    task: TaskSpec,
    slot: int = 0,
    infra: Infrastructure | None = None,
) -> WorkerProcess:
    """Wire a :class:`WorkerProcess` for ``settings.worker.backend``.

    Args:
        settings: Resolved process settings (``worker.backend`` required).
        task: Task specification used when judging runs (campaign space task).
        slot: Worker slot index (concurrency).
        infra: Optional shared infrastructure; created and owned by the caller when omitted.

    Returns:
        A fully injected worker ready for ``serve_forever``.

    Raises:
        ValueError: If ``worker.backend`` is unset.
        roboprobe.core.errors.PluginError: Unknown or incompatible backend plugin.
    """
    if settings.worker.backend is None:
        msg = "worker.backend is required to build a worker"
        raise ValueError(msg)
    infrastructure = build_infrastructure(settings) if infra is None else infra
    backend = get_backend(settings.worker.backend, settings)
    uow_factory = cast("Callable[[], UnitOfWorkPort]", infrastructure.uow_factory)
    metrics = create_metrics(enabled=settings.observability.metrics_enabled)
    return WorkerProcess(
        backend=cast("SimulatorBackendPort", backend),
        uow_factory=uow_factory,
        queue=cast("RunQueuePort", infrastructure.queue),
        artifact_store=cast("ArtifactStorePort", infrastructure.artifact_store),
        verdict_engine=VerdictEngine(
            create_all(settings.oracles),
            direct_rho=backend.capabilities.direct_rho,
        ),
        clock=SystemClock(),
        worker_settings=settings.worker,
        storage_settings=settings.storage,
        task=task,
        metrics=metrics,
        slot=slot,
    )
