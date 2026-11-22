"""Router registry — each router task appends exactly one import + list entry.

Implements: T-080a
"""

from __future__ import annotations

from fastapi import APIRouter

from roboprobe.api.routers import (
    analysis,
    campaigns,
    events,
    experiment_charts,
    experiments,
    health,
    meta,
    modes,
    reports,
    runs,
    spaces,
    sut_profiles,
    traces,
    workers,
)

__all__ = ["ROUTERS"]

ROUTERS: list[APIRouter] = [
    health.router,
    meta.router,
    events.router,
    spaces.router,
    sut_profiles.router,
    campaigns.router,
    runs.router,
    modes.router,
    analysis.router,
    experiments.router,
    reports.router,
    workers.router,
    traces.router,
    experiment_charts.router,
]
