"""ReplayBackend: return a stored trace (docs/05 §2.2).

Implements: FR-ORC-006
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import ClassVar
from uuid import UUID

import numpy as np

from roboprobe.backends.base import (
    PLUGIN_API_VERSION,
    BackendCapabilities,
    EpisodeRequest,
    EpisodeResult,
    MaterializedScenario,
)
from roboprobe.backends.kinematic2d.backend import K2D_SUPPORTED_PARAMS
from roboprobe.backends.trace_io import read_trace, write_trace
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import NavStatus, Trace

__all__ = ["ReplayBackend"]

_TYPICAL_EPISODE_WALL_S = 0.05
_MAX_PARALLEL = 32


class ReplayBackend:
    """Return a pre-recorded trace for oracle re-evaluation and tests."""

    PLUGIN_API_VERSION: ClassVar[int] = PLUGIN_API_VERSION

    def __init__(
        self,
        settings: RoboProbeSettings,
        traces: Mapping[UUID, Path] | None = None,
    ) -> None:
        """``traces`` maps ``run_id`` to a parquet path (tests); production uses workdir."""
        del settings
        self._traces = dict(traces or {})
        self.capabilities = BackendCapabilities(
            name="replay",
            supported_params=K2D_SUPPORTED_PARAMS,
            deterministic=True,
            typical_episode_wall_s=_TYPICAL_EPISODE_WALL_S,
            max_parallel_per_host=_MAX_PARALLEL,
        )

    def prepare(self) -> None:
        """No-op."""

    def materialize(self, req: EpisodeRequest) -> MaterializedScenario:
        """Record the source trace path in ``files``."""
        source = self._traces.get(req.run_id, req.workdir / "trace.parquet")
        return MaterializedScenario(files={"trace": source}, payload={"source": str(source)})

    def run_episode(
        self,
        req: EpisodeRequest,
        materialized: MaterializedScenario,
        on_progress: Callable[[float], None] | None = None,
    ) -> EpisodeResult:
        """Read the stored trace and copy it into ``req.workdir``."""
        del on_progress
        try:
            source = materialized.files["trace"]
            trace = read_trace(source)
            dest = req.workdir / "trace.parquet"
            if dest.resolve() != source.resolve():
                req.workdir.mkdir(parents=True, exist_ok=True)
                write_trace(trace, dest)
            return EpisodeResult(
                trace=trace,
                artifacts={"trace": dest},
                backend_meta={"backend": "replay"},
            )
        except Exception as exc:
            return EpisodeResult(
                trace=_replay_placeholder(req),
                artifacts={},
                backend_meta={"backend": "replay"},
                infra_error=str(exc),
            )

    def cancel(self) -> None:
        """No-op: replay is instantaneous."""

    def shutdown(self) -> None:
        """No-op."""


_PLACEHOLDER_SAMPLES = 2
_PLACEHOLDER_DT_S = 0.05


def _replay_placeholder(req: EpisodeRequest) -> Trace:
    n = _PLACEHOLDER_SAMPLES
    zeros = np.zeros(n, dtype=np.float64)
    t = np.arange(n, dtype=np.float64) * _PLACEHOLDER_DT_S
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
        nav_status=np.full(n, np.int8(NavStatus.ABORTED), dtype=np.int8),
        goal_x=req.task.goal.x,
        goal_y=req.task.goal.y,
        meta={"backend": "replay"},
    )
