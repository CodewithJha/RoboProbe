"""API composition root stub (filled in T-080a).

Layer: Application (L3) — composition root.

Implements: T-046
"""

from __future__ import annotations

from dataclasses import dataclass

from roboprobe.bootstrap._infra import Infrastructure, build_infrastructure
from roboprobe.core.errors import NotFoundError
from roboprobe.core.settings import RoboProbeSettings

__all__ = ["ApiServices", "build_api"]


@dataclass(frozen=True, slots=True)
class ApiServices:
    """Placeholder API collaborators until FastAPI routers land (T-080a)."""

    settings: RoboProbeSettings
    infra: Infrastructure

    def close(self) -> None:
        """Dispose pooled DB connections."""
        self.infra.close()


def build_api(settings: RoboProbeSettings) -> ApiServices:
    """Wire persistence for the API process; app factory arrives in T-080a.

    Raises:
        NotFoundError: Always until T-080a implements ``create_app`` — callers of
            ``roboprobe api`` surface this as a clear runtime message.
    """
    del settings
    msg = "API composition root is not implemented yet (T-080a)"
    raise NotFoundError(msg, context={"task": "T-080a"})


def build_api_infra(settings: RoboProbeSettings) -> ApiServices:
    """Construct API infrastructure without the FastAPI app (tests / future wiring)."""
    return ApiServices(settings=settings, infra=build_infrastructure(settings))
