"""Gazebo/Nav2 SimulatorBackend adapter (T-096b, FR-SIM-003, FR-RUN-005)."""

from __future__ import annotations

import os
import shutil
import threading
from collections.abc import Callable
from enum import StrEnum
from typing import ClassVar

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from roboprobe.backends.base import (
    PLUGIN_API_VERSION,
    BackendCapabilities,
    EpisodeRequest,
    EpisodeResult,
    MaterializedScenario,
)
from roboprobe.backends.gazebo_nav2.bags import clear_episode_bag, find_episode_bag
from roboprobe.backends.gazebo_nav2.materialize import (
    EpisodeSeeds,
    GazeboMaterializer,
    _find_package,
)
from roboprobe.backends.gazebo_nav2.process import EpisodeProcess, ProcessExit, ProcessState
from roboprobe.backends.gazebo_nav2.slots import Slot, SlotAllocator, SlotsExhaustedError
from roboprobe.backends.trace_io import read_trace
from roboprobe.core.errors import EpisodeLaunchError, NotFoundError, ValidationError
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import NavStatus, Trace
from roboprobe.scenario._documents import load_yaml_document, read_document
from roboprobe.scenario.repo_root import discover_repo_root

__all__ = ["GAZEBO_SUPPORTED_PARAMS", "GazeboNav2Backend", "InfraReason"]

_BACKEND = "gazebo_nav2"
_RESULT = "episode_done.json"
_TRACE = "trace.parquet"
_EXIT_CODES = "episode_exit_codes.yaml"
GAZEBO_SUPPORTED_PARAMS = frozenset(
    {
        "robot.max_speed",
        "obstacle.clearance",
        "env.illuminance",
        "sensor.lidar_noise_std",
        "env.floor_friction",
        "comms.cmd_delay_ms",
        "obstacle.along_path",
        "sensor.lidar_dropout",
    }
)


class InfraReason(StrEnum):
    """Stable F-INFRA reasons returned by the Gazebo backend."""

    STARTUP_TIMEOUT = "gazebo_startup_timeout"
    SPAWN_FAILED = "gazebo_spawn_failed"
    INTERNAL_ERROR = "gazebo_internal_error"
    LAUNCH_FAILED = "gazebo_launch_failed"
    WALL_TIMEOUT = "gazebo_wall_timeout"
    CANCELED = "gazebo_canceled"
    RESULT_INVALID = "gazebo_episode_result_invalid"
    TRACE_INVALID = "gazebo_trace_invalid"
    BAG_INVALID = "gazebo_bag_invalid"


class _Status(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    ABORTED = "ABORTED"
    CANCELED = "CANCELED"
    TIMEOUT = "TIMEOUT"
    STARTUP_TIMEOUT = "STARTUP_TIMEOUT"
    SPAWN_FAILED = "SPAWN_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


_INFRA_STATUS = {
    _Status.STARTUP_TIMEOUT: InfraReason.STARTUP_TIMEOUT,
    _Status.SPAWN_FAILED: InfraReason.SPAWN_FAILED,
    _Status.INTERNAL_ERROR: InfraReason.INTERNAL_ERROR,
}


class _ExitCodes(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    completed: int
    startup_timeout: int
    spawn_failed: int
    internal_error: int

    def classify(self, returncode: int | None) -> InfraReason | None:
        """Recognise infrastructure codes separately from launch wrapper failures."""
        if returncode in (None, self.completed):
            return None
        return {
            self.startup_timeout: InfraReason.STARTUP_TIMEOUT,
            self.spawn_failed: InfraReason.SPAWN_FAILED,
            self.internal_error: InfraReason.INTERNAL_ERROR,
        }.get(returncode, InfraReason.LAUNCH_FAILED)


class _Report(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    status: _Status
    sim_time_s: float = Field(ge=0)
    wall_time_s: float = Field(ge=0)
    rtf_mean: float = Field(ge=0)
    recoveries: int = Field(ge=0)


def _failed(req: EpisodeRequest, reason: InfraReason) -> EpisodeResult:
    # The backend port requires a trace for every result. InfraCheck rejects this placeholder.
    xy = np.asarray([req.task.start.x, req.task.start.y, req.task.start.yaw], dtype=np.float64)
    zeros = np.zeros(2, dtype=np.float64)
    return EpisodeResult(
        trace=Trace(
            t=np.asarray([0.0, 1.0]),
            gt_x=np.full(2, xy[0]),
            gt_y=np.full(2, xy[1]),
            gt_yaw=np.full(2, xy[2]),
            est_x=np.full(2, xy[0]),
            est_y=np.full(2, xy[1]),
            est_yaw=np.full(2, xy[2]),
            cmd_v=zeros.copy(),
            cmd_w=zeros.copy(),
            meas_v=zeros.copy(),
            meas_w=zeros.copy(),
            min_obstacle_dist=zeros.copy(),
            contact=np.zeros(2, dtype=np.bool_),
            roll=zeros.copy(),
            pitch=zeros.copy(),
            nav_status=np.full(2, NavStatus.ABORTED.value, dtype=np.int8),
            goal_x=req.task.goal.x,
            goal_y=req.task.goal.y,
            meta={"backend": _BACKEND},
        ),
        artifacts={"log": req.workdir / "episode.log"},
        backend_meta={"backend": _BACKEND},
        infra_error=reason.value,
    )


class GazeboNav2Backend:
    """Use per-episode ROS process groups, with file-based results and typed infra errors."""

    PLUGIN_API_VERSION: ClassVar[int] = PLUGIN_API_VERSION

    def __init__(self, settings: RoboProbeSettings) -> None:
        """Retain the worker configuration; defer all ROS imports to runtime."""
        self._settings = settings
        self._gazebo = settings.backends.gazebo_nav2
        self._root = discover_repo_root()
        self._process = EpisodeProcess(
            self._gazebo, poll_interval_s=settings.worker.poll_interval_s
        )
        self._cancel = threading.Event()
        self._busy = threading.Lock()
        self._slots = SlotAllocator(
            settings.storage.workdir_root,
            domain_id_base=self._gazebo.domain_id_base,
            capacity=self._gazebo.max_parallel_per_host,
            worker_id=f"{settings.worker.id_prefix}:{os.getpid()}",
        )
        self.capabilities = BackendCapabilities(
            name=_BACKEND,
            supported_params=GAZEBO_SUPPORTED_PARAMS,
            deterministic=False,
            typical_episode_wall_s=settings.worker.default_wall_timeout_s,
            max_parallel_per_host=self._gazebo.max_parallel_per_host,
        )

    def prepare(self) -> None:
        """Verify the worker image has sourced ROS and installed the launch package."""
        if shutil.which("ros2") is None:
            msg = "ros2 is unavailable; source the Jazzy and RoboProbe setups"
            raise EpisodeLaunchError(msg)
        installed = _find_package(self._gazebo.launch_package)
        read_document(installed / "launch" / self._gazebo.launch_file)

    def materialize(self, req: EpisodeRequest) -> MaterializedScenario:
        """Prepare the scenario input directory and apply the run's time and bag policy."""
        policy = self._gazebo.record_bag
        record = policy == "always" or (policy == "failures" and req.record_bag)
        gazebo = self._gazebo.model_copy(update={"record_bag": "always" if record else "never"})
        return GazeboMaterializer(
            gazebo,
            req.sut_profile,
            req.task,
            repo_root=self._root,
            wall_timeout_s=req.wall_timeout_s,
            spawn_tolerance_m=self._settings.oracles.infra.spawn_tolerance_m,
            sim_time_budget_s=req.sim_time_budget_s,
        ).materialize(req.scenario, req.workdir, EpisodeSeeds(run=req.seed))

    def run_episode(
        self,
        req: EpisodeRequest,
        materialized: MaterializedScenario,
        on_progress: Callable[[float], None] | None = None,
    ) -> EpisodeResult:
        """Launch ROS, tear down its group and verify the recorder's terminal files."""
        with self._busy:
            self._cancel.clear()
            while not self._cancel.is_set():
                try:
                    with self._slots.reserve() as slot:
                        return self._run(req, materialized, on_progress, slot)
                except SlotsExhaustedError:
                    self._cancel.wait(self._settings.worker.poll_interval_s)
            return _failed(req, InfraReason.CANCELED)

    def _run(
        self,
        req: EpisodeRequest,
        materialized: MaterializedScenario,
        on_progress: Callable[[float], None] | None,
        slot: Slot,
    ) -> EpisodeResult:
        limit = materialized.payload.get("time_limit_s")
        if isinstance(limit, bool) or not isinstance(limit, int | float) or limit <= 0:
            return _failed(req, InfraReason.RESULT_INVALID)
        workdir = req.workdir.resolve()
        for stale_output in (_RESULT, _TRACE):
            (workdir / stale_output).unlink(missing_ok=True)
        try:
            clear_episode_bag(workdir)
        except OSError:
            return _failed(req, InfraReason.BAG_INVALID)
        timeout = min(
            req.wall_timeout_s,
            limit / self._gazebo.physics.real_time_factor
            + self._gazebo.startup_timeout_s
            + self._gazebo.wall_margin_s,
        )
        try:
            process = self._process.run(
                [
                    "ros2",
                    "launch",
                    self._gazebo.launch_package,
                    self._gazebo.launch_file,
                    f"workdir:={workdir}",
                    f"headless:={str(self._gazebo.headless_rendering).lower()}",
                ],
                workdir=workdir,
                env=self._episode_env(slot),
                wall_timeout_s=timeout,
                cancel=self._cancel,
                on_progress=on_progress,
            )
        except OSError:
            return _failed(req, InfraReason.LAUNCH_FAILED)
        return self._result(
            req, process, record_bag=materialized.payload.get("record_bag") == "always"
        )

    def _episode_env(self, slot: Slot) -> dict[str, str]:
        env = dict(os.environ)
        env.update(slot.environment(), RMW_IMPLEMENTATION=self._gazebo.rmw)
        if self._gazebo.software_rendering:
            env["LIBGL_ALWAYS_SOFTWARE"] = "1"
        return env

    def _load_exit_codes(self) -> _ExitCodes:
        catalog = self._root / self._gazebo.topics_file
        path = catalog.with_name(_EXIT_CODES)
        if not path.is_file():
            path = _find_package(self._gazebo.launch_package) / "config" / _EXIT_CODES
        return _ExitCodes.model_validate(load_yaml_document(read_document(path), source=str(path)))

    def _process_error(self, process: ProcessExit) -> InfraReason | None:
        if process.state is ProcessState.WALL_TIMEOUT:
            return InfraReason.WALL_TIMEOUT
        if process.state is not ProcessState.EXITED:
            return None
        try:
            return self._load_exit_codes().classify(process.returncode)
        except (NotFoundError, PydanticValidationError, ValidationError):
            return InfraReason.RESULT_INVALID

    def _result(
        self, req: EpisodeRequest, process: ProcessExit, *, record_bag: bool
    ) -> EpisodeResult:
        reason = self._process_error(process)
        if reason is not None:
            return _failed(req, reason)
        result_path = req.workdir / _RESULT
        try:
            summary = _Report.model_validate_json(result_path.read_bytes())
        except (OSError, PydanticValidationError):
            absent = (
                InfraReason.CANCELED
                if process.state is ProcessState.CANCELED
                else InfraReason.RESULT_INVALID
            )
            return _failed(req, absent)
        status_error = _INFRA_STATUS.get(summary.status)
        if status_error is not None:
            return _failed(req, status_error)
        trace_path = req.workdir / _TRACE
        try:
            trace = read_trace(trace_path)
        except (OSError, NotFoundError, ValidationError):
            return _failed(req, InfraReason.TRACE_INVALID)
        artifacts = {
            "trace": trace_path,
            "log": req.workdir / "episode.log",
            "episode_done": result_path,
        }
        if record_bag:
            try:
                bag = find_episode_bag(req.workdir)
            except OSError:
                bag = None
            if bag is None:
                return _failed(req, InfraReason.BAG_INVALID)
            artifacts["bag"] = bag
        return EpisodeResult(
            trace=trace,
            artifacts=artifacts,
            backend_meta={key: str(value) for key, value in summary.model_dump().items()}
            | {"backend": _BACKEND},
        )

    def cancel(self) -> None:
        """Wake the supervisor so it can stop the owned process group."""
        self._cancel.set()

    def shutdown(self) -> None:
        """Stop the active episode before the worker disposes its resources."""
        self.cancel()
        with self._busy:
            pass
