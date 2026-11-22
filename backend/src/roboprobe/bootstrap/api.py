"""API composition root: infrastructure, plugin catalogue, FastAPI app.

Layer: Application (L3) — composition root.

Implements: T-080a, T-046
"""

from __future__ import annotations

import importlib
import importlib.metadata
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml
from sqlalchemy.engine import Engine

from roboprobe.backends.registry import ENTRY_POINT_GROUP, get_backend
from roboprobe.bootstrap._infra import Infrastructure, UowFactory, build_infrastructure
from roboprobe.bootstrap.idempotency import SqlAlchemyIdempotencyStore
from roboprobe.bootstrap.report_jobs import SqlReportJobs
from roboprobe.core.clock import SystemClock
from roboprobe.core.errors import NotFoundError
from roboprobe.core.metrics_registry import Metrics, create_metrics
from roboprobe.core.settings import RoboProbeSettings, load_settings
from roboprobe.oracles.registry import BUILTIN_ORACLES
from roboprobe.reporting.report_jobs import ReportJobStore
from roboprobe.runner.analysis_jobs import AnalysisJobRunner
from roboprobe.runner.confirmations import ConfirmationService
from roboprobe.runner.lifecycle import CampaignService
from roboprobe.runner.ports import UnitOfWorkPort
from roboprobe.scenario.repo_root import discover_repo_root
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.selection import registry as strategy_registry
from roboprobe.store.artifacts import LocalArtifactStore
from roboprobe.store.engine import session_factory

__all__ = ["ApiServices", "build_api", "build_api_infra", "create_api_app"]


@dataclass(frozen=True, slots=True)
class ApiServices:
    """Wired collaborators for the API process."""

    settings: RoboProbeSettings
    infra: Infrastructure
    metrics: Metrics
    campaigns: CampaignService
    analysis: AnalysisJobRunner
    report_jobs: ReportJobStore
    space_root: Path
    idempotency: object | None = None
    confirmations: ConfirmationService | None = None
    plugin_catalog: dict[str, Any] = field(default_factory=dict)

    @property
    def engine(self) -> Engine:
        """SQLAlchemy engine."""
        return self.infra.engine

    @property
    def uow_factory(self) -> UowFactory:
        """Unit-of-work factory."""
        return self.infra.uow_factory

    @property
    def artifact_store(self) -> LocalArtifactStore:
        """Local artefact store."""
        return self.infra.artifact_store

    def close(self) -> None:
        """Dispose pooled DB connections and background pools."""
        self.analysis._executor.shutdown(wait=False, cancel_futures=True)
        self.report_jobs._executor.shutdown(wait=False, cancel_futures=True)
        self.infra.close()


def build_api(settings: RoboProbeSettings) -> ApiServices:
    """Wire persistence, metrics and plugin catalogues for the API process."""
    infra = build_infrastructure(settings)
    metrics = create_metrics(enabled=settings.observability.metrics_enabled)
    uow_factory = cast("Callable[[], UnitOfWorkPort]", infra.uow_factory)
    campaigns = CampaignService(uow_factory)
    root = discover_repo_root()

    def load_space(space_id: str, version: str) -> ScenarioSpace:
        with infra.uow_factory() as uow:
            row = uow.spaces.get(space_id, version)
        if row is None:
            msg = "registered scenario space not found"
            raise NotFoundError(msg)
        return ScenarioSpace.from_text(
            yaml.safe_dump(row.definition), source="registered campaign space", base_dir=root
        )

    pool = ThreadPoolExecutor(max_workers=settings.runner.analysis.max_workers)
    analysis = AnalysisJobRunner(
        uow_factory,
        infra.artifact_store,
        settings,
        pool,
        SystemClock(),
        campaigns=campaigns,
        engine=infra.engine,
        space_root=root,
        load_space=load_space,
    )
    return ApiServices(
        settings=settings,
        infra=infra,
        metrics=metrics,
        campaigns=campaigns,
        analysis=analysis,
        report_jobs=ReportJobStore(
            ThreadPoolExecutor(max_workers=settings.api.report_workers),
            persistence=SqlReportJobs(session_factory(infra.engine)),
        ),
        space_root=root,
        idempotency=SqlAlchemyIdempotencyStore(session_factory(infra.engine)),
        confirmations=ConfirmationService(
            uow_factory,
            interaction=settings.analysis.interaction,
            confirm_priority=settings.runner.confirm_priority,
            load_space=load_space,
        ),
        plugin_catalog=_plugin_catalog(settings),
    )


def build_api_infra(settings: RoboProbeSettings) -> ApiServices:
    """Construct API infrastructure without building the FastAPI app."""
    return build_api(settings)


def create_api_app(settings: RoboProbeSettings | None = None) -> Any:  # noqa: ANN401
    """Composition-root entry: build services and attach them to ``create_app``.

    Uses ``importlib`` so ``cli → bootstrap`` does not form a static edge to the sibling
    ``api`` package (import-linter layers).
    """
    create_app = importlib.import_module("roboprobe.api.app").create_app
    resolved = settings if settings is not None else load_settings()
    services = build_api(resolved)
    app = create_app(resolved)
    app.state.services = services
    app.state.metrics = services.metrics
    app.state.recover_reports = services.report_jobs.recover
    return app


def _plugin_catalog(settings: RoboProbeSettings) -> dict[str, Any]:
    backends: list[dict[str, Any]] = []
    for ep in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP):
        try:
            backend = get_backend(ep.name, settings)
            caps = backend.capabilities
            backends.append(
                {
                    "name": caps.name,
                    "capabilities": {
                        "supported_params": sorted(caps.supported_params),
                        "deterministic": caps.deterministic,
                        "typical_episode_wall_s": caps.typical_episode_wall_s,
                        "max_parallel_per_host": caps.max_parallel_per_host,
                    },
                }
            )
        except Exception:
            backends.append({"name": ep.name, "capabilities": {}})

    strategies = [
        {
            "name": info.id,
            "description": info.description,
            "params_schema": info.params_schema,
        }
        for info in strategy_registry.describe()
    ]
    oracles = [{"name": name} for name in sorted(BUILTIN_ORACLES)]
    analyzers = [
        {"name": ep.name} for ep in importlib.metadata.entry_points(group="roboprobe.analyzers")
    ]
    return {
        "backends": backends,
        "strategies": strategies,
        "oracles": oracles,
        "analyzers": analyzers,
    }
