"""Build and plugin catalogue (``GET /api/v1/meta``).

Implements: T-080a
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from roboprobe import __version__
from roboprobe.runner.manifest import resolve_git_metadata

__all__ = ["router"]

router = APIRouter(tags=["meta"])


@router.get("/meta")
def meta(request: Request) -> dict[str, Any]:
    """Return version, git SHA and registered plugins."""
    git_sha, _dirty = resolve_git_metadata()
    catalog = getattr(request.app.state.services, "plugin_catalog", {})
    settings = request.app.state.settings
    return {
        "version": __version__,
        "git_sha": git_sha,
        "api_version": "v1",
        "limits": {
            "max_budget": settings.runner.max_budget,
            "max_batch_size": settings.runner.max_batch_size,
            "max_manual_repeats": settings.runner.max_manual_repeats,
            "page_limit_max": settings.api.page_limit_max,
            "heartbeat_timeout_s": settings.runner.heartbeat_timeout_s,
            "risk_max_resolution": settings.risk.max_slice_resolution,
        },
        "defaults": {"risk_slice_resolution": settings.risk.slice_resolution},
        "backends": catalog.get("backends", []),
        "strategies": catalog.get("strategies", []),
        "oracles": catalog.get("oracles", []),
        "analyzers": catalog.get("analyzers", []),
    }
