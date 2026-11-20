"""Default test-selection hyper-parameters (docs/27 §4.7, docs/07 §6.3).

Layer: Kernel (L1). Campaigns may override these; resolved values are snapshotted per campaign.
"""

import itertools
import math
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from roboprobe.core.settings._base import SettingsSection

BenchmarkFunction = Literal["branin_falsify", "multi_mode_6d"]

__all__ = [
    "AcquisitionDefaults",
    "AnalyticBenchmarkDefaults",
    "CemDefaults",
    "GpDefaults",
    "GridDefaults",
    "OfatDefaults",
    "ProbeDefaults",
    "ProbeWeights",
    "SelectionDefaults",
]

_MIN_LEVELS = 2


class ProbeWeights(SettingsSection):
    """Phase mixture of S-PROBE after warm-up; must sum to 1."""

    mode_search: float = Field(default=0.6, ge=0, le=1, description="Mode-search share.")
    boundary: float = Field(default=0.25, ge=0, le=1, description="Boundary-refinement share.")
    refine: float = Field(default=0.15, ge=0, le=1, description="Local refinement share.")

    @model_validator(mode="after")
    def _check_sum(self) -> Self:
        if not math.isclose(self.mode_search + self.boundary + self.refine, 1.0):
            msg = "selection.probe.weights must sum to 1"
            raise ValueError(msg)
        return self


class ProbeDefaults(SettingsSection):
    """S-PROBE strategy defaults."""

    n0_fraction: float = Field(
        default=0.1, gt=0, le=1, description="Warm-up share of the budget [0-1]."
    )
    n0_min_factor: int = Field(
        default=2, ge=1, description="Minimum warm-up runs as a multiple of the dimension d."
    )
    weights: ProbeWeights = Field(default_factory=ProbeWeights)
    epsilon: float = Field(default=0.05, ge=0, le=1, description="Random exploration share.")
    lambda_div: float = Field(default=1.0, ge=0, description="Diversity penalty weight.")
    kappa_radius: float = Field(
        default=0.5, gt=0, description="Diversity radius in GP length-scales."
    )
    beta_straddle: float = Field(default=1.96, gt=0, description="Straddle (LSE) beta.")
    refine_bisect_steps: int = Field(default=4, ge=0, description="Boundary bisection steps.")
    refine_perturb_n: int = Field(default=4, ge=0, description="Perturbations per refined point.")
    refine_perturb_std: float = Field(
        default=0.05, gt=0, description="Perturbation std in the unit cube."
    )
    adapt_window: int = Field(default=20, gt=0, description="Window for phase-weight adaptation.")
    adapt_shift: float = Field(
        default=0.2,
        gt=0,
        le=1,
        description="Weight moved from ModeSearch to Boundary after an unproductive window.",
    )
    mode_search_floor: float = Field(
        default=0.2,
        ge=0,
        le=1,
        description="Lower bound on ModeSearch weight after adaptive shifts.",
    )


class GpDefaults(SettingsSection):
    """Gaussian-process surrogate defaults."""

    max_points: int = Field(default=1500, gt=0, description="Training points kept by the GP.")
    noise_lower_bound: float = Field(default=1e-4, gt=0, description="Likelihood noise floor.")
    torch_threads: int = Field(default=4, ge=1, description="Torch intra-op threads.")


class AcquisitionDefaults(SettingsSection):
    """Acquisition-function optimiser defaults (BoTorch `optimize_acqf`)."""

    num_restarts: int = Field(default=10, gt=0, description="Optimiser restarts.")
    raw_samples: int = Field(default=512, gt=0, description="Raw samples for initialisation.")
    maxiter: int = Field(default=200, gt=0, description="Optimiser iterations.")
    dedupe_tol: float = Field(
        default=1e-3, gt=0, description="Distance under which candidates are duplicates."
    )


class OfatDefaults(SettingsSection):
    """One-factor-at-a-time baseline defaults."""

    levels: tuple[float, ...] = Field(
        default=(0.0, 0.25, 0.5, 0.75, 1.0),
        description="Levels in the unit interval, strictly increasing.",
    )

    @field_validator("levels")
    @classmethod
    def _check_levels(cls, levels: tuple[float, ...]) -> tuple[float, ...]:
        if len(levels) < _MIN_LEVELS:
            msg = f"selection.ofat.levels needs at least {_MIN_LEVELS} levels"
            raise ValueError(msg)
        in_unit = all(0 <= x <= 1 for x in levels)
        if not in_unit or any(a >= b for a, b in itertools.pairwise(levels)):
            msg = "selection.ofat.levels must be strictly increasing values in [0, 1]"
            raise ValueError(msg)
        return levels


class GridDefaults(SettingsSection):
    """Grid baseline defaults."""

    min_levels: int = Field(default=2, ge=_MIN_LEVELS, description="Minimum levels per axis.")


class CemDefaults(SettingsSection):
    """S-CEM cross-entropy rare-event defaults (docs/07 §8)."""

    round_size: int = Field(default=20, gt=0, description="Samples drawn per CEM update round.")
    elite_fraction: float = Field(
        default=0.2, gt=0, le=1, description="Fraction of lowest-rho samples kept as elite."
    )
    n_components: int = Field(
        default=1, ge=1, description="Number of truncated-Gaussian mixture components."
    )
    min_std: float = Field(
        default=0.05,
        gt=0,
        le=1,
        description="Floor on per-dimension proposal std in the unit cube.",
    )


class AnalyticBenchmarkDefaults(SettingsSection):
    """Analytic benchmark functions + BenchmarkBackend knobs (docs/07 §9)."""

    function: BenchmarkFunction = Field(
        default="multi_mode_6d",
        description="Analytic robustness function evaluated by the benchmark backend.",
    )
    noise: float = Field(
        default=0.02,
        ge=0,
        description="Observation noise std for multi_mode_6d (ignored by branin_falsify).",
    )
    typical_episode_wall_s: float = Field(
        default=0.001, gt=0, description="Typical wall time of one analytic episode [s]."
    )
    max_parallel_per_host: int = Field(
        default=32, gt=0, description="Analytic episodes allowed in parallel on one host."
    )
    trace_samples: int = Field(
        default=2, ge=2, description="Synthetic trace length written for each episode."
    )
    trace_dt_s: float = Field(default=0.05, gt=0, description="Synthetic trace sample period [s].")
    failure_volume_target: float = Field(
        default=0.007,
        gt=0,
        lt=1,
        description="Expected failure volume fraction of multi_mode_6d under Sobol QMC.",
    )
    failure_volume_atol: float = Field(
        default=0.002,
        gt=0,
        description="Absolute tolerance on the QMC failure-volume estimate.",
    )
    volume_qmc_power: int = Field(
        default=16,
        ge=8,
        le=24,
        description="Sobol sample count is 2**volume_qmc_power for the volume gate.",
    )


class SelectionDefaults(SettingsSection):
    """Defaults for every selection strategy."""

    probe: ProbeDefaults = Field(default_factory=ProbeDefaults)
    gp: GpDefaults = Field(default_factory=GpDefaults)
    acq: AcquisitionDefaults = Field(default_factory=AcquisitionDefaults)
    ofat: OfatDefaults = Field(default_factory=OfatDefaults)
    grid: GridDefaults = Field(default_factory=GridDefaults)
    cem: CemDefaults = Field(default_factory=CemDefaults)
    benchmarks: AnalyticBenchmarkDefaults = Field(default_factory=AnalyticBenchmarkDefaults)
    mode_cache_refresh_every: int = Field(
        default=10, gt=0, description="Refresh the failure-mode cache every N observations."
    )
    propose_timeout_s: float = Field(
        default=10.0, gt=0, description="Time limit for `propose` before falling back [s]."
    )
