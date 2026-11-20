"""Strategy checkpoint save/restore (Memento) for campaign resume.

Implements: T-041b, NFR-REL-002
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

from roboprobe.core.types import JsonValue
from roboprobe.runner.ports import UowFactory
from roboprobe.selection.base import Strategy

__all__ = ["CheckpointStore"]


class CheckpointStore:
    """Persist and restore ``strategy.state_dict()`` via the UoW port."""

    def __init__(
        self,
        uow_factory: UowFactory,
        *,
        record_factory: Callable[..., object] | None = None,
    ) -> None:
        """Inject UoW factory and optional StrategyStateRecord factory."""
        self._uow_factory = uow_factory
        self._record_factory = record_factory or _default_record

    def save(self, campaign_id: UUID, strategy: Strategy, *, n_obs: int) -> None:
        """Upsert the JSON-serialisable strategy checkpoint."""
        state = _jsonable(strategy.state_dict())
        with self._uow_factory() as uow:
            uow.strategy_states.upsert(
                self._record_factory(campaign_id=campaign_id, n_obs=n_obs, state=state)
            )
            uow.commit()

    def restore(self, campaign_id: UUID, strategy: Strategy) -> bool:
        """Load checkpoint into ``strategy`` if present; return whether one was found."""
        with self._uow_factory() as uow:
            row = uow.strategy_states.get(campaign_id)
        if row is None:
            return False
        strategy.load_state_dict(dict(row.state))
        return True


def _jsonable(state: Mapping[str, Any]) -> dict[str, JsonValue]:
    out: dict[str, JsonValue] = {}
    for key, value in state.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
        elif isinstance(value, dict):
            out[key] = _jsonable(value)
        elif isinstance(value, (list, tuple)):
            out[key] = list(value)
        else:
            out[key] = str(value)
    return out


def _default_record(*, campaign_id: UUID, n_obs: int, state: dict[str, JsonValue]) -> object:
    return importlib.import_module("roboprobe.store.records").StrategyStateRecord(
        campaign_id=campaign_id, n_obs=n_obs, state=state
    )
