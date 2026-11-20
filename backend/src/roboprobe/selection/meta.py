"""Domain-side ``/meta`` hook for strategy catalogues (docs/12 §2, T-060).

The M7 API router can re-export :func:`strategies_payload` without importing registry
internals. No FastAPI dependency here.
"""

from __future__ import annotations

from typing import Any

from roboprobe.selection.registry import describe

__all__ = ["strategies_payload"]


def strategies_payload() -> list[dict[str, Any]]:
    """JSON-ready strategy list for ``GET /api/v1/meta``."""
    return [info.model_dump() for info in describe()]
