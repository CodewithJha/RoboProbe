"""Kinematic2D SimulatorBackend adapter (docs/05 §2.2).

Implements: FR-RUN-006, FR-SCN-005
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

import numpy as np

from roboprobe.backends.base import (
    PLUGIN_API_VERSION,
    BackendCapabilities,
    EpisodeRequest,
    EpisodeResult,
    MaterializedScenario,
)
from roboprobe.backends.kinematic2d.episode import PARAM_ALONG, PARAM_DROPOUT, run_k2d_episode
from roboprobe.backends.kinematic2d.model import Kinematic2DModel
from roboprobe.backends.kinematic2d.world import (
    dump_world_json,
    load_world,
    nominal_path_polyline,
    world_document,
)
from roboprobe.backends.trace_io import write_trace
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import NavStatus, Trace
from roboprobe.perturbation.perception import PerceptionModel
from roboprobe.scenario.materialize import place_obstacle, side_sign

__all__ = ["K2D_SUPPORTED_PARAMS", "Kinematic2DBackend"]

K2D_SUPPORTED_PARAMS: frozenset[str] = frozenset(
    {
        "robot.max_speed",
        "obstacle.clearance",
        "env.illuminance",
        "sensor.lidar_noise_std",
        "env.floor_friction",
        "comms.cmd_delay_ms",
        PARAM_ALONG,
        PARAM_DROPOUT,
    }
)

_TYPICAL_EPISODE_WALL_S = 2.0
_MAX_PARALLEL = 8
_EMPTY_SAMPLES = 2
_EMPTY_DT_S = 0.05


class Kinematic2DBackend:
    """In-process kinematic2d backend."""

    PLUGIN_API_VERSION: ClassVar[int] = PLUGIN_API_VERSION

    def __init__(self, settings: RoboProbeSettings) -> None:
        """Load model and perception files from settings."""
        self._settings = settings
        self._k2d = settings.backends.kinematic2d
        self._model = Kinematic2DModel.from_yaml(Path(self._k2d.model_file))
        self._perception = PerceptionModel.from_yaml(
            Path(settings.backends.gazebo_nav2.perception_model_file)
        )
        self._cancel = threading.Event()
        self.capabilities = BackendCapabilities(
            name="kinematic2d",
            supported_params=K2D_SUPPORTED_PARAMS,
            deterministic=True,
            typical_episode_wall_s=_TYPICAL_EPISODE_WALL_S,
            max_parallel_per_host=_MAX_PARALLEL,
        )

    def prepare(self) -> None:
        """No-op: the backend is in-process."""

    def materialize(self, req: EpisodeRequest) -> MaterializedScenario:
        """Write world JSON and resolved obstacle pose (byte-identical for equal inputs)."""
        req.workdir.mkdir(parents=True, exist_ok=True)
        world_path = req.workdir / "world.json"
        world_path.write_text(dump_world_json(self._model), encoding="utf-8")
        path = nominal_path_polyline(self._model.world)
        obstacle: dict[str, float] | None = None
        if req.task.injected_obstacles:
            spec = req.task.injected_obstacles[0]
            along = float(req.scenario.values.get(spec.placement.along, 0.5))
            lateral = float(req.scenario.values.get(spec.placement.lateral, 0.8))
            pose = place_obstacle(path, along, lateral, side_sign(spec.placement.side))
            obstacle = {"x": pose.x, "y": pose.y, "yaw": pose.yaw}
        obstacle_path = req.workdir / "obstacle.json"
        obstacle_path.write_text(
            json.dumps(obstacle, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        payload = world_document(self._model)
        if obstacle is not None:
            payload["obstacle"] = obstacle
        return MaterializedScenario(
            files={"world": world_path, "obstacle": obstacle_path},
            payload=payload,
        )

    def run_episode(
        self,
        req: EpisodeRequest,
        materialized: MaterializedScenario,
        on_progress: Callable[[float], None] | None = None,
    ) -> EpisodeResult:
        """Run the k2d loop; infrastructure errors populate ``infra_error``."""
        del on_progress
        self._cancel.clear()
        artifacts: dict[str, Path] = {}
        try:
            world = load_world(materialized.files["world"])
            path = nominal_path_polyline(self._model.world)
            trace = run_k2d_episode(
                world,
                req.task,
                req.scenario.values,
                self._model,
                self._k2d,
                req.seed,
                perception=self._perception,
                path=path,
                sim_time_budget_s=req.sim_time_budget_s,
                cancel=self._cancel,
            )
            trace_path = req.workdir / "trace.parquet"
            write_trace(trace, trace_path)
            log_path = req.workdir / "episode.log"
            log_path.write_text("kinematic2d episode complete\n", encoding="utf-8")
            artifacts = {"trace": trace_path, "log": log_path, "world": materialized.files["world"]}
            return EpisodeResult(
                trace=trace,
                artifacts=artifacts,
                backend_meta={
                    "k2d_model_version": self._model.id,
                    "backend": "kinematic2d",
                },
            )
        except Exception as exc:
            return EpisodeResult(
                trace=_placeholder_trace(req),
                artifacts=artifacts,
                backend_meta={"k2d_model_version": self._model.id},
                infra_error=str(exc),
            )

    def cancel(self) -> None:
        """Request cooperative stop of the in-flight episode."""
        self._cancel.set()

    def shutdown(self) -> None:
        """No-op."""


def _placeholder_trace(req: EpisodeRequest) -> Trace:
    n = _EMPTY_SAMPLES
    zeros = np.zeros(n, dtype=np.float64)
    t = np.arange(n, dtype=np.float64) * _EMPTY_DT_S
    t[1] = max(t[1], t[0] + _EMPTY_DT_S)
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
        meta={"backend": "kinematic2d"},
    )
