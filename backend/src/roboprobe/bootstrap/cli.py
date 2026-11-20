"""CLI composition root: settings → adapters → application services.

Layer: Application (L3) — composition root.

Implements: T-046, NFR-EXT-001, NFR-EXT-002
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from roboprobe.bootstrap._infra import Infrastructure, build_infrastructure
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.runner.lifecycle import CampaignService
from roboprobe.runner.ports import UnitOfWorkPort
from roboprobe.store.uow import SqlAlchemyUnitOfWork

__all__ = ["CliServices", "build_cli_services"]


@dataclass(frozen=True, slots=True)
class CliServices:
    """Collaborators every CLI command needs (docs/34 §3)."""

    settings: RoboProbeSettings
    infra: Infrastructure
    campaigns: CampaignService

    @property
    def uow_factory(self) -> Callable[[], UnitOfWorkPort]:
        """Unit-of-work factory bound to the process engine."""
        return cast("Callable[[], UnitOfWorkPort]", self.infra.uow_factory)

    def make_uow(self) -> SqlAlchemyUnitOfWork:
        """Open one Unit of Work (caller uses ``with``)."""
        return self.infra.uow_factory()

    def close(self) -> None:
        """Dispose pooled DB connections."""
        self.infra.close()


def build_cli_services(settings: RoboProbeSettings) -> CliServices:
    """Wire CLI services from ``settings`` (plain constructor injection)."""
    infra = build_infrastructure(settings)
    uow_factory = cast("Callable[[], UnitOfWorkPort]", infra.uow_factory)
    return CliServices(
        settings=settings,
        infra=infra,
        campaigns=CampaignService(uow_factory),
    )
