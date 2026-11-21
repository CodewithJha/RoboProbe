"""Router registry — each router task appends exactly one import + list entry.

Implements: T-080a
"""

from __future__ import annotations

from fastapi import APIRouter

from roboprobe.api.routers import events, health, meta, spaces, sut_profiles

__all__ = ["ROUTERS"]

ROUTERS: list[APIRouter] = [
    health.router,
    meta.router,
    events.router,
    spaces.router,
    sut_profiles.router,
]
