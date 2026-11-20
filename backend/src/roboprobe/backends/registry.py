"""Load simulator backends from ``roboprobe.backends`` entry points (docs/05 §2.1).

Implements: FR-RUN-006, NFR-EXT-001
"""

from __future__ import annotations

import importlib.metadata

from roboprobe.backends.base import PLUGIN_API_VERSION, SimulatorBackend
from roboprobe.core import errors
from roboprobe.core.settings import RoboProbeSettings

__all__ = ["ENTRY_POINT_GROUP", "get_backend"]

ENTRY_POINT_GROUP = "roboprobe.backends"


def get_backend(name: str, settings: RoboProbeSettings) -> SimulatorBackend:
    """Instantiate the backend registered as ``name``.

    Raises:
        roboprobe.core.errors.PluginError: Unknown name or ``PLUGIN_API_VERSION`` mismatch.
    """
    selected = [
        ep for ep in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP) if ep.name == name
    ]
    available = sorted(ep.name for ep in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP))
    if not selected:
        msg = f"unknown backend {name!r}; available: {available}"
        raise errors.PluginError(msg, context={"name": name, "available": ", ".join(available)})
    cls = selected[0].load()
    version = getattr(cls, "PLUGIN_API_VERSION", None)
    if version != PLUGIN_API_VERSION:
        msg = f"backend {name!r} declares PLUGIN_API_VERSION {version!r}, need {PLUGIN_API_VERSION}"
        raise errors.PluginError(
            msg,
            context={"name": name, "plugin_api_version": version, "expected": PLUGIN_API_VERSION},
        )
    backend: SimulatorBackend = cls(settings)
    return backend
