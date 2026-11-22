"""Overlay a verified base Nav2 configuration (T-096a, FR-SIM-003)."""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import numpy as np
import yaml
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from roboprobe.core.errors import ValidationError
from roboprobe.core.types import JsonValue
from roboprobe.geometry import PolygonFootprint
from roboprobe.scenario._documents import load_yaml_document, read_document
from roboprobe.scenario.sut_profile import GazeboNav2ProfileConfig

__all__ = ["Nav2ParamOverlay", "PatchedNav2Params"]

_SEGMENT = re.compile(r"([^\[\].]+)(?:\[([0-9]+)\])?")
_PARAMETERS = "ros__parameters"
_DOCUMENT = TypeAdapter(dict[str, JsonValue])


@dataclass(frozen=True, slots=True)
class PatchedNav2Params:
    """Generated parameter YAML and actual controller rate for the delay node."""

    content: str
    controller_frequency_hz: float
    footprint: dict[str, JsonValue]


def _merge(destination: dict[str, JsonValue], overlay: dict[str, JsonValue]) -> None:
    for key, value in overlay.items():
        existing = destination.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            _merge(existing, value)
        else:
            destination[key] = deepcopy(value)


def _segments(path: str) -> list[str | int]:
    parts: list[str | int] = []
    for component in path.split("."):
        matched = _SEGMENT.fullmatch(component)
        if matched is None:
            msg = f"invalid Nav2 speed parameter path: {path}"
            raise ValidationError(msg)
        parts.append(matched[1])
        if matched[2] is not None:
            parts.append(int(matched[2]))
    return parts


def _set_speed(params: dict[str, JsonValue], path: str, speed: float) -> None:
    *parents, leaf = _segments(path)
    branch: JsonValue = params
    for part in parents:
        match branch, part:
            case dict(), str():
                branch = branch.get(part)
            case list(), int() if part < len(branch):
                branch = branch[part]
            case _:
                branch = None
                break
    match branch, leaf:
        case dict(), str() if type(branch.get(leaf)) in (float, int):
            branch[leaf] = speed
        case list(), int() if leaf < len(branch) and type(branch[leaf]) in (float, int):
            branch[leaf] = speed
        case _:
            msg = f"Nav2 speed parameter does not point to a numeric value: {path}"
            raise ValidationError(msg)


def _map_at(params: dict[str, JsonValue], *keys: str) -> dict[str, JsonValue]:
    branch = params
    for key in keys:
        value = branch.get(key)
        if not isinstance(value, dict):
            msg = f"Nav2 parameters require a mapping at {'.'.join(keys)}"
            raise ValidationError(msg)
        branch = value
    return branch


def _add_depth(params: dict[str, JsonValue], topic: str) -> None:
    costmap = _map_at(params, "local_costmap", "local_costmap", _PARAMETERS)
    voxel = _map_at(costmap, "voxel_layer")
    plugins = costmap.get("plugins")
    sources = voxel.get("observation_sources")
    if (
        not isinstance(plugins, list)
        or "voxel_layer" not in plugins
        or not isinstance(sources, str)
    ):
        msg = "Nav2 local costmap must configure voxel_layer with observation_sources"
        raise ValidationError(msg)
    voxel["enabled"] = True
    voxel["observation_sources"] = " ".join(dict.fromkeys([*sources.split(), "depth"]))
    _merge(
        voxel,
        {
            "depth": {
                "data_type": "PointCloud2",
                "topic": topic,
                "marking": True,
                "clearing": False,
            }
        },
    )


def _positive_number(value: JsonValue, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not (math.isfinite(value) and value > 0)
    ):
        msg = f"Nav2 {name} must be a finite positive value"
        raise ValidationError(msg)
    return float(value)


def _footprint(params: dict[str, JsonValue]) -> dict[str, JsonValue]:
    costmap = _map_at(params, "local_costmap", "local_costmap", _PARAMETERS)
    footprint = costmap.get("footprint")
    if footprint and footprint != "[]":
        try:
            points = json.loads(footprint) if isinstance(footprint, str) else footprint
            polygon = PolygonFootprint(np.asarray(points, dtype=np.float64))
        except (ValueError, TypeError) as exc:
            msg = "Nav2 footprint must contain a valid robot polygon"
            raise ValidationError(msg) from exc
        return {"vertices_m": cast("list[JsonValue]", polygon.vertices.tolist())}
    return {"radius_m": _positive_number(costmap.get("robot_radius"), "robot_radius")}


def _route_velocity(params: dict[str, JsonValue], topic: str, stamped: bool) -> None:
    for node in (
        "controller_server",
        "behavior_server",
        "velocity_smoother",
        "collision_monitor",
        "docking_server",
    ):
        if node in params:
            _map_at(params, node, _PARAMETERS)["enable_stamped_cmd_vel"] = stamped
    _map_at(params, "collision_monitor", _PARAMETERS)["cmd_vel_out_topic"] = topic


class Nav2ParamOverlay:
    """Deep-merge the profile, apply speed limits, and route the processed depth cloud."""

    def __init__(self, source: Path, profile: GazeboNav2ProfileConfig) -> None:
        """Store the base path and validated overlays."""
        self._source = source
        self._profile = profile

    def patch(
        self,
        *,
        speed_mps: float,
        depth_topic: str,
        command_output_topic: str | None = None,
        stamped_cmd_vel: bool = False,
    ) -> PatchedNav2Params:
        """Generate sorted YAML and fail if the selected profile disagrees with the base."""
        document = load_yaml_document(read_document(self._source), source=str(self._source))
        try:
            params = _DOCUMENT.validate_python(document)
        except PydanticValidationError as exc:
            msg = f"{self._source}: invalid Nav2 parameter mapping"
            raise ValidationError(msg) from exc
        _merge(params, self._profile.nav2_overrides)
        for path in self._profile.speed_param_paths:
            _set_speed(params, path, speed_mps)
        _add_depth(params, depth_topic)
        if command_output_topic is not None:
            _route_velocity(params, command_output_topic, stamped_cmd_vel)
        controller = _map_at(params, "controller_server", _PARAMETERS)
        return PatchedNav2Params(
            content=yaml.safe_dump(params, sort_keys=True),
            controller_frequency_hz=_positive_number(
                controller.get("controller_frequency"), "controller_frequency"
            ),
            footprint=_footprint(params),
        )
