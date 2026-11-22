"""Deterministic SDF lighting, friction, and pallet patches (T-096a, FR-SIM-003)."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from lxml import etree  # type: ignore[import-untyped]

from roboprobe.core.errors import ValidationError
from roboprobe.core.types import Pose2D
from roboprobe.scenario._documents import read_document

__all__ = ["PalletPlacement", "PatchedWorld", "SdfPatcher"]

_COLOR_COMPONENTS = 4
_MODEL_NAME = re.compile(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]*")
_GROUND_COLLISION = "./model[@name='ground_plane']/link/collision[geometry/plane]"
_LIGHTING = "./scene/ambient | ./light[@type='directional' or @type='point']/diffuse"


@dataclass(frozen=True, slots=True)
class PalletPlacement:
    """One resolved model name, planar pose and box height."""

    model: str
    pose: Pose2D
    height_m: float


@dataclass(frozen=True, slots=True)
class PatchedWorld:
    """Generated world bytes and the world name used for the ROS bridge."""

    content: bytes
    name: str


def _number(value: float) -> str:
    return f"{value:.15g}"


def _set_text(parent: etree._Element, name: str, text: str) -> None:
    child = _child(parent, name)
    child.text = text


def _child(parent: etree._Element, name: str) -> etree._Element:
    child = parent.find(name)
    return child if child is not None else etree.SubElement(parent, name)


def _scale_color(node: etree._Element, scale: float) -> None:
    msg = f"SDF {node.tag} must contain four finite RGBA components"
    try:
        values = [float(part) for part in (node.text or "").split()]
    except ValueError as exc:
        raise ValidationError(msg) from exc
    if len(values) != _COLOR_COMPONENTS or not all(map(math.isfinite, values)):
        raise ValidationError(msg)
    red, green, blue, alpha = values
    node.text = " ".join(map(_number, (red * scale, green * scale, blue * scale, alpha)))


def _append_pallet(world: etree._Element, pallet: PalletPlacement, index: int) -> None:
    if not _MODEL_NAME.fullmatch(pallet.model):
        msg = "SDF pallet model must be a local model name"
        raise ValidationError(msg, context={"model": pallet.model})
    include = etree.SubElement(world, "include")
    _set_text(include, "uri", f"model://{pallet.model}")
    _set_text(include, "name", f"{pallet.model}_{index}")
    x, y, yaw = pallet.pose.x, pallet.pose.y, pallet.pose.yaw
    _set_text(include, "pose", " ".join(map(_number, (x, y, pallet.height_m / 2, 0, 0, yaw))))


class SdfPatcher:
    """Patch an operator-selected world without expanding XML entities or loading DTDs."""

    def __init__(self, source: Path) -> None:
        """Store the path to the unmodified source SDF."""
        self._source = source

    def patch(
        self,
        *,
        lighting_scale: float,
        floor_friction: float,
        real_time_factor: float,
        pallets: Sequence[PalletPlacement],
    ) -> PatchedWorld:
        """Generate a world from the same base on every call."""
        raw = read_document(self._source)
        # DTD loading, entity expansion, and parser network access are disabled before parse.
        parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
        try:
            root = etree.fromstring(raw, parser=parser)
        except etree.XMLSyntaxError as exc:
            msg = f"{self._source}: invalid SDF"
            raise ValidationError(msg) from exc
        if root.getroottree().docinfo.doctype:
            msg = f"{self._source}: SDF DOCTYPE declarations are forbidden"
            raise ValidationError(msg)
        worlds = root.findall("./world") if root.tag == "sdf" else []
        if len(worlds) != 1 or not worlds[0].get("name"):
            msg = f"{self._source}: SDF must contain exactly one named world"
            raise ValidationError(msg)
        world = worlds[0]
        ground = world.xpath(_GROUND_COLLISION)
        if not ground:
            msg = f"{self._source}: SDF has no ground plane collision"
            raise ValidationError(msg)
        for collision in ground:
            friction = _child(_child(_child(collision, "surface"), "friction"), "ode")
            _set_text(friction, "mu", _number(floor_friction))
            _set_text(friction, "mu2", _number(floor_friction))
        for color in world.xpath(_LIGHTING):
            _scale_color(color, lighting_scale)
        _set_text(_child(world, "physics"), "real_time_factor", _number(real_time_factor))
        for index, pallet in enumerate(pallets):
            _append_pallet(world, pallet, index)
        return PatchedWorld(
            content=cast("bytes", etree.tostring(root, encoding="UTF-8", xml_declaration=True)),
            name=cast("str", world.get("name")),
        )
