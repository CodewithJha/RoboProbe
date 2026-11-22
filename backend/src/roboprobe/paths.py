"""Filesystem anchors for Alembic and other backend-relative assets."""

from __future__ import annotations

from pathlib import Path


def backend_root() -> Path:
    """Directory that contains ``alembic.ini`` (dev tree or ``/app`` in the image)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "alembic.ini").is_file():
            return parent
    docker = Path("/app")
    if (docker / "alembic.ini").is_file():
        return docker
    msg = "alembic.ini not found"
    raise RuntimeError(msg)
