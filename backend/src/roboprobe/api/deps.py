"""FastAPI dependency providers; override in tests via ``app.dependency_overrides``.

Implements: T-080a
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Protocol, cast

from fastapi import Request

from roboprobe.core.settings import RoboProbeSettings
from roboprobe.runner.lifecycle import CampaignService

__all__ = [
    "ArtifactStoreProto",
    "ServicesProto",
    "UowFactory",
    "get_artifact_store",
    "get_services",
    "get_settings",
    "get_uow",
]


class ArtifactStoreProto(Protocol):
    """Narrow artefact-store surface used by routers."""

    @property
    def root(self) -> object:
        """Artefact filesystem root."""
        ...

    def open(self, ref: object) -> object:
        """Open a stored blob."""
        ...


class ServicesProto(Protocol):
    """API collaborators attached at startup (bootstrap)."""

    settings: RoboProbeSettings
    uow_factory: Callable[[], object]
    artifact_store: ArtifactStoreProto
    metrics: object
    plugin_catalog: dict[str, object]
    campaigns: CampaignService
    analysis: Any
    report_jobs: Any
    space_root: Path

    def close(self) -> None:
        """Release process resources."""
        ...


UowFactory = Callable[[], object]


def get_settings(request: Request) -> RoboProbeSettings:
    """Return process settings from ``app.state``."""
    return request.app.state.settings  # type: ignore[no-any-return]


def get_services(request: Request) -> ServicesProto:
    """Return the composition-root services object."""
    return request.app.state.services  # type: ignore[no-any-return]


def get_uow(request: Request) -> Iterator[object]:
    """Yield a unit of work and close it after the request."""
    services: ServicesProto = request.app.state.services
    uow = services.uow_factory()
    if callable(getattr(uow, "__enter__", None)):
        with cast("AbstractContextManager[object]", uow) as entered:
            yield entered
        return
    try:
        yield uow
    finally:
        close = getattr(uow, "close", None)
        if callable(close):
            close()


def get_artifact_store(request: Request) -> ArtifactStoreProto:
    """Return the artefact store from services."""
    return request.app.state.services.artifact_store  # type: ignore[no-any-return]
