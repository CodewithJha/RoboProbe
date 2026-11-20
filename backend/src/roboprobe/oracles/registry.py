"""Oracle plugin registry (entry-point group ``roboprobe.oracles``).

Implements: FR-ORC-001
"""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Mapping, Sequence
from importlib.metadata import entry_points
from typing import Final

from roboprobe.core.errors import PluginError
from roboprobe.core.settings import OracleThresholds
from roboprobe.oracles.base import Oracle

__all__ = ["BUILTIN_ORACLES", "OracleRegistry", "create_all"]

_GROUP: Final = "roboprobe.oracles"

BUILTIN_ORACLES: Final[Mapping[str, str]] = {
    "O-CLEAR": "roboprobe.oracles.clearance:ClearanceOracle",
    "O-GOAL": "roboprobe.oracles.goal:GoalOracle",
    "O-PROG": "roboprobe.oracles.progress:ProgressOracle",
    "O-LOC": "roboprobe.oracles.localization:LocalizationOracle",
    "O-NAV": "roboprobe.oracles.nav:NavStatusOracle",
    "O-STAB": "roboprobe.oracles.stability:StabilityOracle",
    "O-OSC": "roboprobe.oracles.oscillation:OscillationOracle",
}


def _load_class(spec: str) -> type[Oracle]:
    module_name, _, attr = spec.partition(":")
    module = importlib.import_module(module_name)
    loaded = getattr(module, attr)
    if not isinstance(loaded, type) or not issubclass(loaded, Oracle):
        msg = f"{spec} is not an Oracle subclass"
        raise PluginError(msg, context={"spec": spec})
    return loaded


class OracleRegistry:
    """Discover oracle plugins and reject API-version mismatches."""

    def __init__(self, extra: Mapping[str, type[Oracle]] | None = None) -> None:
        """Load built-ins, then entry points, then ``extra`` (tests)."""
        classes: dict[str, type[Oracle]] = {
            oracle_id: _load_class(spec) for oracle_id, spec in BUILTIN_ORACLES.items()
        }
        for ep in entry_points().select(group=_GROUP):
            loaded = ep.load()
            if not isinstance(loaded, type) or not issubclass(loaded, Oracle):
                msg = f"entry point {ep.name!r} is not an Oracle subclass"
                raise PluginError(msg, context={"name": ep.name})
            self._check_api(loaded, ep.name)
            classes[loaded.id] = loaded
        if extra:
            for cls in extra.values():
                self._check_api(cls, cls.id)
                classes[cls.id] = cls
        for cls in classes.values():
            self._check_api(cls, cls.id)
        self._classes = classes

    @staticmethod
    def _check_api(plugin: type[Oracle], name: str) -> None:
        version = getattr(plugin, "PLUGIN_API_VERSION", None)
        if version != Oracle.PLUGIN_API_VERSION:
            msg = f"oracle {name!r} PLUGIN_API_VERSION={version!r} != {Oracle.PLUGIN_API_VERSION}"
            raise PluginError(
                msg,
                context={"name": name, "plugin_api_version": version or 0},
            )

    def create(self, oracle_id: str, thresholds: OracleThresholds) -> Oracle:
        """Instantiate one registered oracle."""
        try:
            cls = self._classes[oracle_id]
        except KeyError as exc:
            msg = f"unknown oracle {oracle_id!r}"
            raise PluginError(msg, context={"oracle_id": oracle_id}) from exc
        return cls(thresholds)

    def create_all(
        self,
        thresholds: OracleThresholds,
        ids: Sequence[str] | None = None,
    ) -> tuple[Oracle, ...]:
        """Instantiate oracles in registry order (or ``ids`` if given)."""
        wanted: Iterable[str] = ids if ids is not None else self._classes
        return tuple(self.create(oracle_id, thresholds) for oracle_id in wanted)


def create_all(thresholds: OracleThresholds) -> tuple[Oracle, ...]:
    """Instantiate every built-in oracle with ``thresholds``."""
    return OracleRegistry().create_all(thresholds)
