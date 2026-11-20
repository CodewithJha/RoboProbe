"""BenchmarkBackend: evaluate analytic rho and emit a synthetic trace (docs/07 §9).

Implements: FR-SEL-002, FR-SEL-003
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import ClassVar

import numpy as np

from roboprobe.backends.base import (
    PLUGIN_API_VERSION,
    BackendCapabilities,
    EpisodeRequest,
    EpisodeResult,
    MaterializedScenario,
)
from roboprobe.backends.trace_io import write_trace
from roboprobe.core.seeding import SIMULATOR, make_rng
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import NavStatus, Trace
from roboprobe.selection.benchmarks import branin_falsify, multi_mode_6d

__all__ = [
    "BENCHMARK_PARAM_ORDER",
    "BRANIN_PARAM_ORDER",
    "MULTI_MODE_PARAM_ORDER",
    "BenchmarkBackend",
]

BRANIN_PARAM_ORDER: tuple[str, ...] = ("robot.u1", "robot.u2")
MULTI_MODE_PARAM_ORDER: tuple[str, ...] = (
    "robot.max_speed",
    "obstacle.clearance",
    "env.illuminance",
    "sensor.lidar_noise_std",
    "env.floor_friction",
    "comms.cmd_delay_ms",
)
BENCHMARK_PARAM_ORDER: tuple[str, ...] = tuple(
    dict.fromkeys([*BRANIN_PARAM_ORDER, *MULTI_MODE_PARAM_ORDER])
)


class BenchmarkBackend:
    """In-process analytic robustness backend with a ``direct_rho`` capability."""

    PLUGIN_API_VERSION: ClassVar[int] = PLUGIN_API_VERSION

    def __init__(self, settings: RoboProbeSettings) -> None:
        """Bind benchmark function and synthetic-trace knobs from settings."""
        self._cfg = settings.selection.benchmarks
        self.capabilities = BackendCapabilities(
            name="benchmark",
            supported_params=frozenset(BENCHMARK_PARAM_ORDER),
            deterministic=True,
            typical_episode_wall_s=self._cfg.typical_episode_wall_s,
            max_parallel_per_host=self._cfg.max_parallel_per_host,
            direct_rho=True,
        )

    def prepare(self) -> None:
        """No-op: evaluation is pure Python."""

    def materialize(self, req: EpisodeRequest) -> MaterializedScenario:
        """Record the function name and unit vector for provenance."""
        unit = _unit_from_values(req.scenario.values, self._param_order())
        return MaterializedScenario(
            files={},
            payload={
                "function": self._cfg.function,
                "unit": [float(x) for x in unit],
            },
        )

    def run_episode(
        self,
        req: EpisodeRequest,
        materialized: MaterializedScenario,
        on_progress: Callable[[float], None] | None = None,
    ) -> EpisodeResult:
        """Evaluate the configured analytic function and write a placeholder trace."""
        del on_progress
        try:
            unit = np.asarray(materialized.payload["unit"], dtype=np.float64)
            rho = self._evaluate(unit, req.seed)
            req.workdir.mkdir(parents=True, exist_ok=True)
            trace = _synthetic_trace(req, self._cfg.trace_samples, self._cfg.trace_dt_s, rho)
            trace_path = req.workdir / "trace.parquet"
            write_trace(trace, trace_path)
            return EpisodeResult(
                trace=trace,
                artifacts={"trace": trace_path},
                backend_meta={
                    "backend": "benchmark",
                    "function": self._cfg.function,
                    "rho": f"{rho:.17g}",
                    "sim_time_s": "0",
                },
            )
        except Exception as exc:
            return EpisodeResult(
                trace=_synthetic_trace(req, self._cfg.trace_samples, self._cfg.trace_dt_s, 0.0),
                artifacts={},
                backend_meta={"backend": "benchmark", "function": self._cfg.function},
                infra_error=str(exc),
            )

    def cancel(self) -> None:
        """No-op: evaluation is instantaneous."""

    def shutdown(self) -> None:
        """No-op."""

    def _param_order(self) -> Sequence[str]:
        if self._cfg.function == "branin_falsify":
            return BRANIN_PARAM_ORDER
        return MULTI_MODE_PARAM_ORDER

    def _evaluate(self, unit: np.ndarray, seed: int) -> float:
        if self._cfg.function == "branin_falsify":
            return branin_falsify(unit)
        rng = make_rng(seed, SIMULATOR) if self._cfg.noise > 0.0 else None
        return multi_mode_6d(unit, noise=self._cfg.noise, rng=rng)


def _unit_from_values(values: Mapping[str, object], order: Sequence[str]) -> np.ndarray:
    missing = [pid for pid in order if pid not in values]
    if missing:
        msg = f"scenario missing benchmark parameters {missing}"
        raise KeyError(msg)
    out = np.empty(len(order), dtype=np.float64)
    for i, pid in enumerate(order):
        raw = values[pid]
        if not isinstance(raw, (int, float)):
            msg = f"benchmark parameter {pid!r} must be numeric, got {type(raw).__name__}"
            raise TypeError(msg)
        out[i] = float(raw)
    return out


def _synthetic_trace(req: EpisodeRequest, n: int, dt_s: float, rho: float) -> Trace:
    zeros = np.zeros(n, dtype=np.float64)
    t = np.arange(n, dtype=np.float64) * dt_s
    goal_x = float(req.task.goal.x)
    goal_y = float(req.task.goal.y)
    return Trace(
        t=t,
        gt_x=zeros.copy(),
        gt_y=zeros.copy(),
        gt_yaw=zeros.copy(),
        est_x=zeros.copy(),
        est_y=zeros.copy(),
        est_yaw=zeros.copy(),
        cmd_v=zeros.copy(),
        cmd_w=zeros.copy(),
        meas_v=zeros.copy(),
        meas_w=zeros.copy(),
        min_obstacle_dist=np.ones(n, dtype=np.float64),
        contact=np.zeros(n, dtype=np.bool_),
        roll=zeros.copy(),
        pitch=zeros.copy(),
        nav_status=np.full(n, NavStatus.SUCCEEDED.value, dtype=np.int8),
        goal_x=goal_x,
        goal_y=goal_y,
        meta={"rho": float(rho), "backend": "benchmark"},
    )
