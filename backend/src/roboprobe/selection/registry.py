"""Strategy plugin registry (entry-point group ``roboprobe.strategies``, ADR-0016).

Implements: FR-SEL-001, NFR-EXT-003
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Final

from roboprobe.core import errors
from roboprobe.selection.base import PLUGIN_API_VERSION, Strategy, StrategyContext
from roboprobe.selection.baselines.grid import GridStrategy
from roboprobe.selection.baselines.lhs import LHSStrategy
from roboprobe.selection.baselines.ofat import OFATStrategy
from roboprobe.selection.baselines.random import RandomStrategy
from roboprobe.selection.baselines.sobol import SobolStrategy

__all__ = ["ENTRY_POINT_GROUP", "available", "create", "get", "register"]

ENTRY_POINT_GROUP: Final = "roboprobe.strategies"

_REGISTRY: dict[str, type[Strategy]] = {}
_ENTRY_POINTS_LOADED = False
_BUILTINS: tuple[type[Strategy], ...] = (
    RandomStrategy,
    LHSStrategy,
    SobolStrategy,
    GridStrategy,
    OFATStrategy,
)


def register(cls: type[Strategy]) -> type[Strategy]:
    """Register a strategy class (also usable as a decorator).

    Args:
        cls: Concrete :class:`Strategy` subclass.

    Returns:
        ``cls`` unchanged.

    Raises:
        roboprobe.core.errors.PluginError: Duplicate id or wrong ``PLUGIN_API_VERSION``.
    """
    strategy_id = getattr(cls, "id", "")
    if not strategy_id:
        msg = f"{cls.__qualname__} is missing ClassVar id"
        raise errors.PluginError(msg, context={"class": cls.__qualname__})
    version = getattr(cls, "PLUGIN_API_VERSION", None)
    if version != PLUGIN_API_VERSION:
        msg = f"{strategy_id} plugin API {version!r} != {PLUGIN_API_VERSION}"
        raise errors.PluginError(
            msg, context={"id": strategy_id, "version": version, "expected": PLUGIN_API_VERSION}
        )
    existing = _REGISTRY.get(strategy_id)
    if existing is not None and existing is not cls:
        msg = f"duplicate strategy id {strategy_id!r}"
        raise errors.PluginError(msg, context={"id": strategy_id})
    _REGISTRY[strategy_id] = cls
    return cls


def available() -> list[str]:
    """Sorted registered strategy ids."""
    _ensure_loaded()
    return sorted(_REGISTRY)


def get(strategy_id: str) -> type[Strategy]:
    """Return the class registered as ``strategy_id``.

    Raises:
        roboprobe.core.errors.PluginError: Unknown id.
    """
    _ensure_loaded()
    try:
        return _REGISTRY[strategy_id]
    except KeyError:
        known = sorted(_REGISTRY)
        msg = f"unknown strategy {strategy_id!r}; available: {known}"
        details = {"id": strategy_id, "available": ", ".join(known)}
        raise errors.PluginError(msg, context=details) from None


def create(strategy_id: str, ctx: StrategyContext) -> Strategy:
    """Instantiate the strategy named ``strategy_id``."""
    return get(strategy_id)(ctx)


def _ensure_loaded() -> None:
    global _ENTRY_POINTS_LOADED  # noqa: PLW0603
    if not _ENTRY_POINTS_LOADED:
        _load_entry_points()
        for cls in _BUILTINS:
            register(cls)
        _ENTRY_POINTS_LOADED = True


def _load_entry_points() -> None:
    for ep in entry_points().select(group=ENTRY_POINT_GROUP):
        register(ep.load())
