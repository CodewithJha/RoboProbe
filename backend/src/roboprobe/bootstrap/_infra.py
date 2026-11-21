"""Shared infrastructure construction for composition roots.

Layer: Application (L3) — composition helpers. Only ``roboprobe.bootstrap`` may import
concrete ``store`` / ``backends`` adapters (docs/16 §2, ADR-0016).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.engine import Engine

from roboprobe.core.settings import RoboProbeSettings
from roboprobe.observability.tracing import configure_tracing, instrument_sqlalchemy
from roboprobe.store.artifacts import LocalArtifactStore
from roboprobe.store.engine import create_engine_from_settings, session_factory
from roboprobe.store.queue_pg import PostgresRunQueue
from roboprobe.store.uow import SqlAlchemyUnitOfWork

__all__ = ["Infrastructure", "build_infrastructure"]

UowFactory = Callable[[], SqlAlchemyUnitOfWork]


@dataclass(frozen=True, slots=True)
class Infrastructure:
    """Engine, UoW factory, queue and artefact store for one process."""

    settings: RoboProbeSettings
    engine: Engine
    uow_factory: UowFactory
    queue: PostgresRunQueue
    artifact_store: LocalArtifactStore

    def close(self) -> None:
        """Dispose the SQLAlchemy engine (call at process shutdown)."""
        self.engine.dispose()


def build_infrastructure(settings: RoboProbeSettings) -> Infrastructure:
    """Construct shared persistence adapters from ``settings``."""
    configure_tracing(settings.observability, settings.observability.service_name or "roboprobe")
    engine = create_engine_from_settings(settings.database)
    instrument_sqlalchemy(engine)
    factory = session_factory(engine)
    channel = settings.database.notify_channel

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(factory, notify_channel=channel)

    queue = PostgresRunQueue(
        factory,
        notify_channel=channel,
        wall_timeout_s=settings.worker.default_wall_timeout_s,
        sim_time_budget_s=settings.worker.default_sim_time_budget_s,
    )
    store = LocalArtifactStore(settings.storage.artifact_root)
    return Infrastructure(
        settings=settings,
        engine=engine,
        uow_factory=uow_factory,
        queue=queue,
        artifact_store=store,
    )
