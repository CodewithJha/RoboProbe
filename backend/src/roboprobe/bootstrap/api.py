"""API composition root: infrastructure, plugin catalogue, FastAPI app.

Layer: Application (L3) — composition root.

Implements: T-080a, T-046
"""

from __future__ import annotations

import importlib
import importlib.metadata
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.engine import Engine

from roboprobe.backends.registry import ENTRY_POINT_GROUP, get_backend
from roboprobe.bootstrap._infra import Infrastructure, UowFactory, build_infrastructure
from roboprobe.core.metrics_registry import Metrics, create_metrics
from roboprobe.core.settings import RoboProbeSettings, load_settings
from roboprobe.oracles.registry import BUILTIN_ORACLES
from roboprobe.selection import registry as strategy_registry
from roboprobe.store.artifacts import LocalArtifactStore

__all__ = ["ApiServices", "build_api", "build_api_infra", "create_api_app"]


@dataclass(frozen=True, slots=True)
class ApiServices:
    """Wired collaborators for the API process."""

    settings: RoboProbeSettings
    infra: Infrastructure
    metrics: Metrics
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
        """Dispose pooled DB connections."""
        self.infra.close()


def build_api(settings: RoboProbeSettings) -> ApiServices:
    """Wire persistence, metrics and plugin catalogues for the API process."""
    infra = build_infrastructure(settings)
    metrics = create_metrics(enabled=settings.observability.metrics_enabled)
    return ApiServices(
        settings=settings,
        infra=infra,
        metrics=metrics,
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
