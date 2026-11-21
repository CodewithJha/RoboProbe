"""Repository root discovery (docs/12, shared by CLI and API).

Implements: T-081
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["discover_repo_root", "resolve_repo_path"]

_SOURCE_LAYOUT_DEPTH = 4


def discover_repo_root(start: Path | None = None) -> Path:
    """Find ``configs/scenario_spaces`` (same rules as CLI)."""
    origin = (start or Path(__file__)).resolve()
    cwd = Path.cwd().resolve()
    seen: set[Path] = set()
    for candidate in (origin, *origin.parents, cwd, *cwd.parents):
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / "configs" / "scenario_spaces").is_dir():
            return candidate
    if len(origin.parents) > _SOURCE_LAYOUT_DEPTH:
        return origin.parents[_SOURCE_LAYOUT_DEPTH]
    return origin


def resolve_repo_path(path: Path) -> Path:
    """Return ``path`` if it exists, else ``discover_repo_root() / path`` when that exists."""
    if path.is_file():
        return path
    resolved = discover_repo_root() / path
    return resolved if resolved.is_file() else path
