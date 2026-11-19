"""Illumination-dependent depth degradation (P3) — docs/06 §3.3.

With illuminance ``L`` the darkness factor is
``η = clip(log10(L_ref / L) / log10(L_ref / L_min), 0, 1)`` (0 bright, 1 darkest). Each depth
ray / point is then degraded with

* valid-return probability ``p_valid = 1 - valid_loss · η²``,
* range noise ``sigma_d = sigma_base + sigma_r2 · r² · (1 + dark_gain · η)``,
* effective maximum range ``r_max = r_max_bright · (1 - dark_reduction · η)``.

All constants come from a versioned YAML file (``configs/perception/oakd_lowlight_v1.yaml``; path
from ``backends.gazebo_nav2.perception_model_file``), never from literals. The ROS
``perception_degrader`` node and kinematic2d share this module (NumPy + PyYAML only).

:meth:`PerceptionModel.degrade` follows the lidar rules (``roboprobe.perturbation.lidar``): pure,
seeded by the caller (the run's ``perception`` stream, docs/21 §3), one normal and one uniform draw
per ray on every call, and non-finite rays pass through unchanged.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Self

import numpy as np
import numpy.typing as npt
import yaml

__all__ = ["PerceptionModel"]

FloatArray = npt.NDArray[np.float64]
_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True, kw_only=True)
class PerceptionModel:
    """Constants of the docs/06 §3.3 depth degradation model.

    Attributes:
        id: Model identifier recorded in run manifests (e.g. ``oakd_lowlight_v1``).
        l_ref_lux: ``L_ref`` — illuminance at or above which ``η = 0`` [lux].
        l_min_lux: ``L_min`` — illuminance at or below which ``η = 1`` [lux].
        valid_loss: Share of returns lost at ``η = 1``.
        sigma_base_m: Range noise floor [m].
        sigma_r2_per_m: Quadratic range-noise growth [1/m].
        sigma_dark_gain: Noise growth with darkness.
        r_max_bright_m: Effective maximum range in bright light [m].
        r_max_dark_reduction: Share of the maximum range lost at ``η = 1``.
    """

    id: str
    l_ref_lux: float
    l_min_lux: float
    valid_loss: float
    sigma_base_m: float
    sigma_r2_per_m: float
    sigma_dark_gain: float
    r_max_bright_m: float
    r_max_dark_reduction: float

    def __post_init__(self) -> None:
        """Validate the constants.

        Raises:
            ValueError: On a non-finite constant or one outside its physical range.
        """
        constants = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "id"}
        problems = [
            f"{name} is not finite" for name, v in constants.items() if not math.isfinite(v)
        ]
        rules = {
            "id must be non-empty": bool(self.id),
            "need 0 < l_min_lux < l_ref_lux": 0.0 < self.l_min_lux < self.l_ref_lux,
            "need 0 <= valid_loss <= 1": 0.0 <= self.valid_loss <= 1.0,
            "need sigma_* >= 0": min(self.sigma_base_m, self.sigma_r2_per_m, self.sigma_dark_gain)
            >= 0.0,
            "need r_max_bright_m > 0": self.r_max_bright_m > 0.0,
            "need 0 <= r_max_dark_reduction < 1": 0.0 <= self.r_max_dark_reduction < 1.0,
        }
        problems += [rule for rule, ok in rules.items() if not ok]
        if problems:
            msg = f"invalid perception model {self.id!r}: {'; '.join(problems)}"
            raise ValueError(msg)

    @classmethod
    def from_yaml(cls, path: Path) -> Self:
        """Load a model file (``schema_version``, ``id``, ``constants`` mapping).

        Raises:
            FileNotFoundError: If ``path`` does not exist.
            ValueError: On invalid YAML, a wrong schema version, missing/unknown/non-numeric
                constants or invalid values.
        """
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            msg = f"{path}: invalid YAML: {exc}"
            raise ValueError(msg) from exc
        if not isinstance(document, dict) or document.get("schema_version") != _SCHEMA_VERSION:
            msg = f"{path}: expected a mapping with schema_version: {_SCHEMA_VERSION}"
            raise ValueError(msg)
        constants = document.get("constants")
        expected = {f.name for f in fields(cls)} - {"id"}
        if not isinstance(constants, dict) or set(constants) != expected:
            got = sorted(constants) if isinstance(constants, dict) else constants
            msg = f"{path}: constants must define exactly {sorted(expected)}, got {got}"
            raise ValueError(msg)
        numeric = {
            k: v
            for k, v in constants.items()
            if isinstance(v, int | float) and not isinstance(v, bool)
        }
        if len(numeric) != len(constants):
            msg = f"{path}: non-numeric constants {sorted(set(constants) - set(numeric))}"
            raise ValueError(msg)
        return cls(id=str(document.get("id", "")), **{k: float(v) for k, v in numeric.items()})

    def eta(self, illuminance: float) -> float:
        """Darkness factor ``η`` in ``[0, 1]`` for an illuminance [lux] ``> 0``.

        Raises:
            ValueError: If ``illuminance`` is not finite and positive.
        """
        if not (math.isfinite(illuminance) and illuminance > 0.0):
            msg = f"illuminance must be finite and > 0 lux, got {illuminance}"
            raise ValueError(msg)
        ratio = math.log10(self.l_ref_lux / illuminance) / math.log10(
            self.l_ref_lux / self.l_min_lux
        )
        return min(1.0, max(0.0, ratio))

    def p_valid(self, eta: float) -> float:
        """Probability that a ray returns a measurement."""
        return 1.0 - self.valid_loss * eta**2

    def sigma_d(self, r: npt.ArrayLike, eta: float) -> FloatArray:
        """Range noise standard deviation [m] at true range ``r`` [m]."""
        r = np.asarray(r, dtype=np.float64)
        return self.sigma_base_m + self.sigma_r2_per_m * r**2 * (1.0 + self.sigma_dark_gain * eta)

    def r_max(self, eta: float) -> float:
        """Effective maximum range [m]."""
        return self.r_max_bright_m * (1.0 - self.r_max_dark_reduction * eta)

    def degrade(
        self, ranges: npt.ArrayLike, illuminance: float, rng: np.random.Generator
    ) -> FloatArray:
        """Degrade true depth ranges for the given illuminance.

        Rays beyond ``r_max`` or failing the ``p_valid`` draw read ``+inf`` (no return); the
        others get Gaussian noise ``sigma_d(r)`` and are floored at 0 m.

        Args:
            ranges: True ranges [m]; any shape. Non-finite entries are passed through.
            illuminance: Ambient illuminance P3 [lux], ``> 0``.
            rng: The run's ``perception`` stream.

        Returns:
            Degraded ranges [m] as a new ``float64`` array.

        Raises:
            ValueError: If ``illuminance`` is not finite and positive.
        """
        eta = self.eta(illuminance)
        values = np.array(ranges, dtype=np.float64)
        z = rng.standard_normal(size=values.shape)
        u = rng.random(size=values.shape)
        finite = np.isfinite(values)
        true = values[finite]
        noisy = np.maximum(true + self.sigma_d(true, eta) * z[finite], 0.0)
        lost = (true > self.r_max(eta)) | (u[finite] >= self.p_valid(eta))
        values[finite] = np.where(lost, np.inf, noisy)
        return values
