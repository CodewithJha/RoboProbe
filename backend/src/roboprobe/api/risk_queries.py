"""Risk slice loading/refitting behind a bounded cache (T-082b, FR-RSK-003)."""

from __future__ import annotations

import importlib
import json
from collections import OrderedDict
from contextlib import nullcontext
from typing import Any
from uuid import UUID

import numpy as np
import yaml

from roboprobe.api.artifact_ref import artifact_ref_from_record
from roboprobe.core.clock import SystemClock
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.risk import RiskMapper, load_slices
from roboprobe.scenario.space import ScenarioSpace

__all__ = ["RiskQueries", "completed_risk_analysis"]


def completed_risk_analysis(uow: Any, campaign_id: UUID) -> Any:
    """Return the newest completed full analysis with risk volume metadata."""
    return next(
        (
            analysis
            for analysis in reversed(uow.analyses.list_for_campaign(campaign_id))
            if analysis.kind in {"final", "full"}
            and analysis.status in {"DONE", "OK", "PARTIAL"}
            and isinstance((analysis.summary or {}).get("volumes"), dict)
        ),
        None,
    )


class RiskQueries:
    """Cache exact slices by analysis id, axes, anchor and resolution."""

    def __init__(self, services: Any) -> None:
        """Bind API collaborators and the configured cache budget."""
        self.services = services
        self.cache: OrderedDict[tuple[object, ...], dict[str, Any]] = OrderedDict()

    def slice(  # noqa: PLR0912, PLR0913, PLR0915, PLR0917 - validate/load/cache/refit pipeline
        self,
        campaign_id: UUID,
        x: str,
        y: str,
        anchor: str,
        resolution: int,
        anchor_values: str | None = None,
    ) -> dict[str, Any]:
        """Load immutable analysis metadata, then use stored NPZ data or refit a GP."""
        created = self.services.uow_factory()
        with (
            created
            if callable(getattr(created, "__enter__", None))
            else nullcontext(created) as uow
        ):
            campaign = uow.campaigns.get(campaign_id)
            if campaign is None:
                msg = "campaign not found"
                raise NotFoundError(msg)
            risk = uow.risk_maps.latest(campaign_id)
            analysis = completed_risk_analysis(uow, campaign_id) if risk is None else None
            if risk is None and analysis is None:
                msg = "Run analysis first; no risk map is available"
                raise NotFoundError(msg)
            key = (
                analysis.id
                if analysis is not None
                else getattr(risk, "analysis_id", None) or getattr(risk, "id", campaign_id),
                x,
                y,
                anchor,
                resolution,
                anchor_values,
            )
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            blob_id = risk.slices_artifact if risk is not None else None
            artifact = uow.artifacts.get(blob_id) if blob_id is not None else None
            stored_slices = []
            if anchor == "nominal" and anchor_values is None and artifact is not None:
                with self.services.artifact_store.open(
                    artifact_ref_from_record(artifact)
                ) as stream:
                    prefix = stream.read(2)
                    stream.seek(0)
                    if prefix == b"PK":
                        stored_slices = load_slices(stream)
                    else:
                        legacy = _legacy_slice(json.load(stream), x, y, resolution)
                        if legacy is not None:
                            return self._cache(key, legacy)
            stored = uow.spaces.get(campaign.space_id, campaign.space_version)
            if stored is None:
                msg = "registered campaign space is missing"
                raise NotFoundError(msg)
            space = ScenarioSpace.from_text(
                yaml.safe_dump(stored.definition),
                source="registered space",
                base_dir=self.services.space_root,
            ).with_pins(campaign.pins)
            ids = {p.id for p in space.params}
            if x == y or x not in ids or y not in ids:
                msg = "slice axes must be distinct free parameters"
                raise ValidationError(msg)
            runs = []
            cursor = None
            while True:
                page = uow.runs.list_for_campaign(campaign_id, limit=None, cursor=cursor)
                runs.extend(page.items)
                cursor = page.next_cursor
                if cursor is None:
                    break
            values = space.nominal_values()
            if anchor != "nominal":
                if not anchor.startswith("mode:"):
                    msg = "anchor must be nominal or mode:<code>"
                    raise ValidationError(msg)
                mode = next(
                    (
                        mode
                        for mode in uow.modes.list_for_campaign(campaign_id)
                        if mode.code == anchor.removeprefix("mode:")
                    ),
                    None,
                )
                medoid = None if mode is None else uow.runs.get(mode.medoid_run_id)
                if medoid is None:
                    msg = "mode anchor has no medoid"
                    raise NotFoundError(msg)
                values = dict(medoid.scenario_values)
            if anchor_values is not None:
                values = _anchor_override(space, values, ids - {x, y}, anchor_values)
            selected = next(
                (
                    item
                    for item in stored_slices
                    if item.x_param == x and item.y_param == y and len(item.x_values) == resolution
                ),
                None,
            )
            if selected is None:
                usable = [
                    r for r in runs if r.robustness is not None and len(r.x_unit) == space.dim
                ]
                if not usable:
                    msg = "Run analysis first; no GP training data is available"
                    raise NotFoundError(msg)
                cls = importlib.import_module("roboprobe.selection.surrogate").RobustnessGP
                gp = cls(
                    space.dim,
                    seed=campaign.seed,
                    gp=self.services.settings.selection.gp,
                    clock=SystemClock(),
                )
                gp.fit(
                    np.asarray([r.x_unit for r in usable]),
                    np.asarray([r.robustness for r in usable]),
                )
                selected = RiskMapper(gp, space, self.services.settings.risk.thresholds).slice(
                    x, y, values, resolution
                )
            result = {
                "x_param": x,
                "y_param": y,
                "anchor": anchor,
                "resolution": resolution,
                "x_values": selected.x_values.tolist(),
                "y_values": selected.y_values.tolist(),
                "p_fail": selected.p_fail.tolist(),
                "region": selected.region.tolist(),
                "log_x": selected.log_x,
                "log_y": selected.log_y,
                "points": [
                    {
                        "x": r.scenario_values[x],
                        "y": r.scenario_values[y],
                        "verdict": getattr(r.verdict, "value", r.verdict),
                        "run_id": str(r.id),
                    }
                    for r in runs
                    if r.verdict is not None and x in r.scenario_values and y in r.scenario_values
                ],
            }
            result["grid"] = {
                field: result[field]
                for field in (
                    "x_values",
                    "y_values",
                    "p_fail",
                    "region",
                    "log_x",
                    "log_y",
                    "points",
                )
            }
            return self._cache(key, result)

    def _cache(self, key: tuple[object, ...], result: dict[str, Any]) -> dict[str, Any]:
        self.cache[key] = result
        while len(self.cache) > self.services.settings.api.slice_cache_size:
            self.cache.popitem(last=False)
        return result


def _legacy_slice(payload: object, x: str, y: str, resolution: int) -> dict[str, Any] | None:
    if not isinstance(payload, list):
        return None
    for grid in payload:
        if (
            isinstance(grid, dict)
            and grid.get("x_param") == x
            and grid.get("y_param") == y
            and grid.get("resolution", resolution) == resolution
        ):
            extras = {
                key: grid[key]
                for key in ("log_x", "log_y", "x_values", "y_values", "p_fail", "points", "region")
                if key in grid
            }
            return {
                "x_param": x,
                "y_param": y,
                "anchor": "nominal",
                "resolution": resolution,
                "grid": grid,
                **extras,
            }
    return None


def _anchor_override(
    space: ScenarioSpace, values: dict[str, Any], allowed: set[str], raw: str
) -> dict[str, Any]:
    try:
        overrides = json.loads(raw)
    except ValueError as exc:
        msg = "anchor_values must be a JSON object"
        raise ValidationError(msg) from exc
    if not isinstance(overrides, dict) or not overrides.keys() <= allowed:
        msg = "anchor_values must contain only non-axis free parameters"
        raise ValidationError(msg)
    result = {**values, **overrides}
    space.to_unit(result)
    return result
