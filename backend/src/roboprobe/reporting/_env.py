"""Shared Jinja2 environment for offline HTML reports.

Implements: T-078b, T-079
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

__all__ = ["template_env", "templates_root"]


def templates_root() -> Path:
    """Filesystem root of packaged Jinja templates."""
    ref = resources.files("roboprobe.reporting") / "templates"
    with resources.as_file(ref) as path:
        return path


def template_env() -> Environment:
    """Strict, auto-escaping Jinja environment."""
    return Environment(
        loader=FileSystemLoader(str(templates_root())),
        autoescape=select_autoescape(("html", "xml", "j2")),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
