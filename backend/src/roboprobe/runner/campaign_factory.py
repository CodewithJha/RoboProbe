"""Shared campaign validation and snapshots (T-081b, FR-API-001, FR-CLI-001)."""

from __future__ import annotations

from collections.abc import Mapping

import pydantic

from roboprobe.core.errors import ErrorCode, PluginError, ValidationError
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.settings.oracles import OracleThresholds
from roboprobe.core.types import JsonValue
from roboprobe.runner.campaign_spec import CampaignCreate
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.selection.registry import get as get_strategy

__all__ = ["CampaignFactory"]


class CampaignFactory:
    """Validate a campaign before persistence, shared by CLI and HTTP adapters."""

    def __init__(self, settings: RoboProbeSettings) -> None:
        """Bind campaign limits and snapshot defaults."""
        self._settings = settings

    def prepare(
        self,
        request: CampaignCreate,
        *,
        space: ScenarioSpace,
        supported_params: frozenset[str],
    ) -> CampaignCreate:
        """Resolve pins, strategy defaults and oracle thresholds before any campaign insert."""
        settings = self._settings
        if request.budget > settings.runner.max_budget:
            msg = f"budget exceeds runner.max_budget ({settings.runner.max_budget})"
            raise ValidationError(msg)
        if request.batch_size > settings.runner.max_batch_size:
            msg = f"batch_size exceeds runner.max_batch_size ({settings.runner.max_batch_size})"
            raise ValidationError(msg)
        pinned = space.with_pins(request.pins)
        unsupported = sorted(p.id for p in pinned.params if p.id not in supported_params)
        if unsupported:
            msg = f"backend does not support parameters: {', '.join(unsupported)}"
            raise ValidationError(
                msg,
                code=ErrorCode.BACKEND_UNSUPPORTED_PARAM,
                context={"parameters": ", ".join(unsupported)},
            )
        try:
            strategy = get_strategy(request.strategy.id)
            unknown = set(request.strategy.params) - strategy.Params.model_fields.keys()
            if unknown:
                msg = f"unknown strategy parameters: {', '.join(sorted(unknown))}"
                raise ValidationError(msg)
            params = strategy.Params.model_validate(request.strategy.params).model_dump(mode="json")
            oracles = OracleThresholds.model_validate(
                _merge(settings.oracles.model_dump(mode="json"), request.oracle_overrides)
            ).model_dump(mode="json")
        except (pydantic.ValidationError, PluginError) as exc:
            raise ValidationError(str(exc)) from exc
        return request.model_copy(
            update={
                "strategy": request.strategy.model_copy(update={"params": params}),
                "oracle_overrides": oracles,
            }
        )


def _merge(
    base: Mapping[str, JsonValue], override: Mapping[str, JsonValue]
) -> dict[str, JsonValue]:
    result = dict(base)
    for key, value in override.items():
        current = result.get(key)
        result[key] = (
            _merge(current, value)
            if isinstance(current, dict) and isinstance(value, dict)
            else value
        )
    return result
