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
    return {
        "version": __version__,
        "git_sha": git_sha,
        "api_version": "v1",
        "backends": catalog.get("backends", []),
        "strategies": catalog.get("strategies", []),
        "oracles": catalog.get("oracles", []),
        "analyzers": catalog.get("analyzers", []),
    }
