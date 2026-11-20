"""SQLAlchemy Unit of Work: one session per ``with`` block (docs/34 §8).

Implements: T-011a
"""

# ruff: noqa: D102, D105, D107

from __future__ import annotations

from types import TracebackType

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from roboprobe.store.engine import SessionFactory
from roboprobe.store.flush import execute
from roboprobe.store.locks import AdvisoryLock
from roboprobe.store.repositories.analyses import SqlAnalysisRepo
from roboprobe.store.repositories.artifacts import SqlArtifactRepo
from roboprobe.store.repositories.campaigns import SqlCampaignRepo
from roboprobe.store.repositories.events import SqlEventRepo
from roboprobe.store.repositories.experiments import SqlExperimentRepo
from roboprobe.store.repositories.modes import SqlFailureModeRepo
from roboprobe.store.repositories.oracle_results import SqlOracleResultRepo
from roboprobe.store.repositories.risk_maps import SqlRiskMapRepo
from roboprobe.store.repositories.runs import SqlRunRepo
from roboprobe.store.repositories.spaces import SqlSpaceRepo
from roboprobe.store.repositories.strategy_states import SqlStrategyStateRepo
from roboprobe.store.repositories.sut_profiles import SqlSutProfileRepo
from roboprobe.store.repositories.workers import SqlWorkerRepo

__all__ = ["SqlAlchemyUnitOfWork"]


class SqlAlchemyUnitOfWork:
    """Implements: UnitOfWork."""

    spaces: SqlSpaceRepo
    sut_profiles: SqlSutProfileRepo
    campaigns: SqlCampaignRepo
    runs: SqlRunRepo
    oracle_results: SqlOracleResultRepo
    strategy_states: SqlStrategyStateRepo
    modes: SqlFailureModeRepo
    risk_maps: SqlRiskMapRepo
    analyses: SqlAnalysisRepo
    experiments: SqlExperimentRepo
    workers: SqlWorkerRepo
    artifacts: SqlArtifactRepo
    events: SqlEventRepo

    def __init__(self, factory: SessionFactory, *, notify_channel: str) -> None:
        self._factory = factory
        self._notify_channel = notify_channel
        self._session: Session | None = None
        self._closed = False
        self._advisory: dict[str, AdvisoryLock] = {}

    def __enter__(self) -> SqlAlchemyUnitOfWork:
        session = self._factory()
        self._session = session
        self._closed = False
        self.spaces = SqlSpaceRepo(session)
        self.sut_profiles = SqlSutProfileRepo(session)
        self.campaigns = SqlCampaignRepo(session)
        self.runs = SqlRunRepo(session)
        self.oracle_results = SqlOracleResultRepo(session)
        self.strategy_states = SqlStrategyStateRepo(session)
        self.modes = SqlFailureModeRepo(session)
        self.risk_maps = SqlRiskMapRepo(session)
        self.analyses = SqlAnalysisRepo(session)
        self.experiments = SqlExperimentRepo(session)
        self.workers = SqlWorkerRepo(session)
        self.artifacts = SqlArtifactRepo(session)
        self.events = SqlEventRepo(session, self._notify_channel)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if not self._closed:
                if exc_type is None:
                    self.commit()
                else:
                    self.rollback()
        finally:
            for key in list(self._advisory):
                self.advisory_unlock(key)
            if self._session is not None:
                self._session.close()
                self._session = None

    def commit(self) -> None:
        self._require().commit()
        self._closed = True

    def rollback(self) -> None:
        self._require().rollback()
        self._closed = True

    def notify(self, channel: str, payload: str) -> None:
        execute(
            self._require(),
            text("SELECT pg_notify(:channel, :payload)"),
            {"channel": channel, "payload": payload},
        )

    def try_advisory_lock(self, key: str) -> bool:
        held = self._advisory.get(key)
        if held is not None and held.held:
            return True
        bind = self._require().get_bind()
        engine = bind if isinstance(bind, Engine) else bind.engine
        lock = AdvisoryLock(engine, key)
        if not lock.acquire():
            return False
        self._advisory[key] = lock
        return True

    def advisory_unlock(self, key: str) -> None:
        lock = self._advisory.pop(key, None)
        if lock is not None:
            lock.release()

    def _require(self) -> Session:
        if self._session is None:
            msg = "UnitOfWork used outside a with-block"
            raise RuntimeError(msg)
        return self._session
