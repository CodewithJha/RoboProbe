"""Liveness and readiness probes (docs/21 §5.4).

Implements: T-080a, NFR-OBS-001
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from roboprobe.api.errors import problem_response
from roboprobe.core.errors import ErrorCode
from roboprobe.paths import backend_root

__all__ = ["router"]

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live() -> dict[str, str]:
    """Process is up."""
    return {"status": "ok"}


@router.get("/health/ready", response_model=None)
def ready(request: Request) -> JSONResponse | dict[str, Any]:
    """DB reachable, migrations at head, artefact root writable."""
    override = getattr(request.app.state, "readiness_failures", None)
    if isinstance(override, list):
        if override:
            return _not_ready(request, override)
        return {"status": "ok", "checks": ["db", "migrations", "artifacts"]}

    failures: list[str] = []
    services = getattr(request.app.state, "services", None)
    if services is None:
        failures.append("services_unavailable")
        return _not_ready(request, failures)

    engine = getattr(services, "engine", None)
    if engine is None:
        failures.append("db_unreachable")
    else:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                context = MigrationContext.configure(conn)
                current = context.get_current_revision()
            cfg = Config()
            cfg.set_main_option("script_location", str(backend_root() / "alembic"))
            head = ScriptDirectory.from_config(cfg).get_current_head()
            if current != head:
                failures.append("migrations_behind")
        except Exception:
            failures.append("db_unreachable")

    settings = getattr(services, "settings", None)
    root = getattr(getattr(settings, "storage", None), "artifact_root", None)
    if root is None:
        failures.append("artifact_root_unwritable")
    else:
        try:
            path = Path(root)
            path.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path, delete=True):
                pass
        except OSError:
            failures.append("artifact_root_unwritable")

    if failures:
        return _not_ready(request, failures)
    return {"status": "ok", "checks": ["db", "migrations", "artifacts"]}


def _not_ready(request: Request, failures: list[str]) -> JSONResponse:
    return problem_response(
        request=request,
        code=ErrorCode.INTERNAL,
        detail=f"readiness checks failed: {', '.join(failures)}",
        status=503,
        title="Service unavailable",
    )
