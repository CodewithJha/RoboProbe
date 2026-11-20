"""Persistence adapters: ORM, repositories, unit of work, artifact store.

Layer: Adapter (infrastructure). See docs/16 §2 for the allowed import directions.
"""

from roboprobe.store.artifacts import (
    ArtifactRef,
    ArtifactStore,
    LocalArtifactStore,
    NullArtifactStore,
)
from roboprobe.store.engine import create_engine_from_settings, session_factory
from roboprobe.store.pagination import Page
from roboprobe.store.ports import RunQueue, UnitOfWork
from roboprobe.store.queue_pg import PostgresRunQueue
from roboprobe.store.uow import SqlAlchemyUnitOfWork

__all__ = [
    "ArtifactRef",
    "ArtifactStore",
    "LocalArtifactStore",
    "NullArtifactStore",
    "Page",
    "PostgresRunQueue",
    "RunQueue",
    "SqlAlchemyUnitOfWork",
    "UnitOfWork",
    "create_engine_from_settings",
    "session_factory",
]
