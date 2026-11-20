"""Strategy plugin registry (entry-point group ``roboprobe.strategies``, ADR-0016).

Implements: FR-SEL-001, FR-SEL-008, NFR-EXT-003
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

from roboprobe.core import errors
from roboprobe.selection.base import PLUGIN_API_VERSION, Strategy, StrategyContext
from roboprobe.selection.baselines.grid import GridStrategy
from roboprobe.selection.baselines.lhs import LHSStrategy
from roboprobe.selection.baselines.ofat import OFATStrategy
from roboprobe.selection.baselines.random import RandomStrategy
from roboprobe.selection.baselines.sobol import SobolStrategy
from roboprobe.selection.bo import BOStrategy
from roboprobe.selection.lse import LevelSetStrategy
from roboprobe.selection.probe import ProbeStrategy

__all__ = [
    "ENTRY_POINT_GROUP",
    "StrategyFamily",
    "StrategyInfo",
    "available",
    "create",
    "describe",
    "get",
    "register",
    "validate_params",
]

ENTRY_POINT_GROUP: Final = "roboprobe.strategies"
StrategyFamily = Literal["baseline", "learning", "plugin"]

_REGISTRY: dict[str, type[Strategy]] = {}
_ENTRY_POINTS_LOADED = False
_BUILTINS: tuple[type[Strategy], ...] = (
    RandomStrategy,
    LHSStrategy,
    SobolStrategy,
    GridStrategy,
    OFATStrategy,
    ProbeStrategy,
    BOStrategy,
    LevelSetStrategy,
)

_DESCRIPTIONS: dict[str, str] = {
    "S-RANDOM": "Draws scenarios at random from each parameter's prior.",
    "S-LHS": "Spreads scenarios evenly across the space with a Latin hypercube.",
    "S-SOBOL": "Walks a low-discrepancy Sobol sequence through the space.",
    "S-GRID": "Evaluates a full factorial grid of every parameter level.",
    "S-OFAT": "Sweeps one parameter at a time while holding the rest at nominal.",
    "S-PROBE": "Learns where failures hide and probes there.",
    "S-BO": "Uses Bayesian optimisation to drive toward low robustness.",
    "S-LSE": "Focuses samples on the pass/fail boundary for sharper risk maps.",
    "S-CEM": "Adapts a rare-event sampler toward the lowest-robustness elite set.",
}

_FAMILIES: dict[str, StrategyFamily] = {
    "S-RANDOM": "baseline",
    "S-LHS": "baseline",
    "S-SOBOL": "baseline",
    "S-GRID": "baseline",
    "S-OFAT": "baseline",
    "S-PROBE": "learning",
    "S-BO": "learning",
    "S-LSE": "learning",
    "S-CEM": "plugin",
}


class StrategyInfo(BaseModel):
    """Wizard / ``/meta`` description of one registered strategy (docs/13 §3.2)."""

    model_config = ConfigDict(frozen=True)

    id: str
    family: StrategyFamily
    description: str
    params_schema: dict[str, Any]


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


def describe() -> list[StrategyInfo]:
    """Return id, family, plain-language blurb and JSON Schema for every strategy."""
    _ensure_loaded()
    infos: list[StrategyInfo] = []
    for strategy_id in available():
        cls = _REGISTRY[strategy_id]
        params_model = cls.Params
        infos.append(
            StrategyInfo(
                id=strategy_id,
                family=_FAMILIES.get(strategy_id, "plugin"),
                description=_DESCRIPTIONS.get(strategy_id, f"Plugin strategy {strategy_id}."),
                params_schema=params_model.model_json_schema(),
            )
        )
    return infos


def validate_params(strategy_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """Validate campaign ``strategy_params`` against the strategy's Params model.

    Args:
        strategy_id: Registered strategy id.
        params: Raw params mapping from the campaign request.

    Returns:
        Normalised params as a plain dict.

    Raises:
        roboprobe.core.errors.ValidationError: Invalid field; ``context["field"]`` holds the path.
    """
    cls = get(strategy_id)
    try:
        return cls.Params.model_validate(params).model_dump()
    except PydanticValidationError as exc:
        error = exc.errors()[0]
        loc = ".".join(str(part) for part in error.get("loc", ()))
        msg = error.get("msg", "invalid strategy params")
        raise errors.ValidationError(
            msg,
            context={"field": loc or "params", "strategy": strategy_id},
        ) from exc


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
