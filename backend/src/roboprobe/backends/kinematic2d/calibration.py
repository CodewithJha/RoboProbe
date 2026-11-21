"""kinematic2d calibration scenarios (FR-SIM-002, T-034).

Loads designed GT canonical unit-cube points from ``backends.kinematic2d.calibration_file``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Self

import pydantic
import yaml
from pydantic import BaseModel, ConfigDict

from roboprobe.core import errors

__all__ = ["K2DGtCalibration", "load_calibration"]


class K2DGtCalibration(BaseModel):
    """Designed failure-mode canonical points for acceptance tests."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int
    space_id: str
    nominal_unit: tuple[float, float, float, float, float, float]
    modes: dict[str, tuple[float, float, float, float, float, float]]

    @classmethod
    def from_yaml(cls, path: Path) -> Self:
        """Load and validate the calibration file."""
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            msg = f"kinematic2d calibration not found: {path}"
            raise errors.NotFoundError(msg, context={"path": str(path)}) from exc
        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            msg = f"{path}: invalid YAML: {exc}"
            raise errors.ValidationError(msg, context={"path": str(path)}) from exc
        if not isinstance(document, dict) or document.get("schema_version") != 1:
            msg = f"{path}: expected mapping with schema_version 1"
            raise errors.ValidationError(msg, context={"path": str(path)})
        try:
            return cls.model_validate(document)
        except (TypeError, pydantic.ValidationError) as exc:
            msg = f"{path}: invalid calibration: {exc}"
            raise errors.ValidationError(
                msg, context={"path": str(path), "reason": str(exc)}
            ) from exc

    def mode_points(self) -> tuple[tuple[str, tuple[float, ...]], ...]:
        """Return ``(GT-*, unit)`` pairs in ``GT-A`` … ``GT-D`` order."""
        order = ("GT-A", "GT-B", "GT-C", "GT-D")
        missing = [label for label in order if label not in self.modes]
        if missing:
            msg = f"calibration missing modes: {', '.join(missing)}"
            raise errors.ValidationError(msg, context={"missing": missing})
        return tuple((label, self.modes[label]) for label in order)


def load_calibration(path: Path) -> K2DGtCalibration:
    """Convenience wrapper around :meth:`K2DGtCalibration.from_yaml`."""
    return K2DGtCalibration.from_yaml(path)
