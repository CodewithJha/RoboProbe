"""HTTP interface: FastAPI application, routers, schemas and server-sent events.

Layer: Interface (L4). See docs/16 §2 for the allowed import directions.

Implements: T-080a
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

    from roboprobe.core.settings import RoboProbeSettings

__all__ = ["create_app"]


def create_app(settings: RoboProbeSettings | None = None) -> FastAPI:
    """Re-export :func:`roboprobe.api.app.create_app` (lazy to keep import light)."""
    from roboprobe.api.app import create_app as _create_app

    return _create_app(settings)
