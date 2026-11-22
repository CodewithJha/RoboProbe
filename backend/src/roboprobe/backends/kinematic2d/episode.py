"""Fixed-step kinematic2d episode loop producing a :class:`Trace` (docs/10 §7).

Implements: FR-SIM-001, NFR-PERF-001, NFR-REP-001
"""

from __future__ import annotations

import math
import threading
from collections.abc import Mapping
from typing import Any

import numpy as np

from roboprobe.backends.kinematic2d.controller import path_arclength, pure_pursuit
from roboprobe.backends.kinematic2d.costmap import inflate, overlay_sensor_hits
from roboprobe.backends.kinematic2d.localization import Localizer, scan_match_gain
from roboprobe.backends.kinematic2d.model import Kinematic2DModel
from roboprobe.backends.kinematic2d.planner import plan_path
from roboprobe.backends.kinematic2d.robot import RobotState, step
from roboprobe.backends.kinematic2d.sensors import DepthCamera, Lidar
from roboprobe.core.seeding import LOCALIZATION, PERCEPTION, SENSOR, make_rng
from roboprobe.core.settings.backends import Kinematic2DSettings
from roboprobe.core.types import NavStatus, ParamValue, TaskSpec, Trace
from roboprobe.geometry import GridRayCaster, OccupancyGrid, Rect, point_rect_distance
from roboprobe.perturbation.delay import CommandDelayBuffer
from roboprobe.perturbation.perception import PerceptionModel
from roboprobe.scenario.materialize import place_obstacle, side_sign
from roboprobe.scenario.task import polyline_length_m, time_limit_s

__all__ = [
    "PARAM_ALONG",
    "PARAM_CLEARANCE",
    "PARAM_DELAY_MS",
    "PARAM_DROPOUT",
    "PARAM_FRICTION",
    "PARAM_ILLUMINANCE",
    "PARAM_LIDAR_NOISE",
    "PARAM_SPEED",
    "run_k2d_episode",
]

PARAM_SPEED = "robot.max_speed"
PARAM_CLEARANCE = "obstacle.clearance"
PARAM_ILLUMINANCE = "env.illuminance"
PARAM_LIDAR_NOISE = "sensor.lidar_noise_std"
PARAM_FRICTION = "env.floor_friction"
PARAM_DELAY_MS = "comms.cmd_delay_ms"
PARAM_ALONG = "obstacle.along_path"
PARAM_DROPOUT = "sensor.lidar_dropout"

_MS_PER_S = 1000.0
_MIN_TRACE_SAMPLES = 2


def _f(values: Mapping[str, ParamValue], key: str, default: float) -> float:
    value = values.get(key, default)
    return float(value)


def _pallet(task: TaskSpec, path: np.ndarray, values: Mapping[str, ParamValue]) -> Rect | None:
    if not task.injected_obstacles:
        return None
    spec = task.injected_obstacles[0]
    along = _f(values, spec.placement.along, 0.5)
    lateral = _f(values, spec.placement.lateral, 0.8)
    pose = place_obstacle(path, along, lateral, side_sign(spec.placement.side))
    length, width, _ = spec.size
    return Rect(x=pose.x, y=pose.y, yaw=pose.yaw, length=length, width=width)


def _at_goal(x: float, y: float, yaw: float, task: TaskSpec) -> bool:
    tol = task.goal_tolerance
    if math.hypot(x - task.goal.x, y - task.goal.y) > tol.xy:
        return False
    err = (yaw - task.goal.yaw + math.pi) % (2.0 * math.pi) - math.pi
    return abs(err) <= tol.yaw


def _global_inflated(world: OccupancyGrid, radius_m: float) -> OccupancyGrid:
    cells = math.ceil(radius_m / world.resolution)
    return OccupancyGrid(inflate(world.occupied, cells), world.resolution, world.origin)


def _circle_clearance(
    world: OccupancyGrid, radius: float, x: float, y: float, pallet: Rect | None
) -> float:
    """Footprint clearance using the precomputed EDT plus an optional pallet rectangle."""
    ox, oy = world.origin
    res = world.resolution
    col = math.floor((x - ox) / res)
    row = math.floor((y - oy) / res)
    rows, cols = world.shape
    if row < 0 or row >= rows or col < 0 or col >= cols:
        dist = 0.0
    else:
        dist = max(float(world.distance_field[row, col]) - radius, 0.0)
    if pallet is not None:
        gap = float(point_rect_distance((x, y), pallet)) - radius
        dist = min(dist, max(gap, 0.0))
    return dist


def run_k2d_episode(  # noqa: PLR0913,PLR0917
    world: OccupancyGrid,
    task: TaskSpec,
    scenario_values: Mapping[str, ParamValue],
    model: Kinematic2DModel,
    settings: Kinematic2DSettings,
    seed: int,
    *,
    perception: PerceptionModel,
    path: np.ndarray,
    sim_time_budget_s: float,
    cancel: threading.Event | None = None,
) -> Trace:
    """Run one deterministic episode and return a columnar :class:`Trace`."""
    return _run(
        world,
        task,
        scenario_values,
        model,
        settings,
        seed,
        perception,
        path,
        sim_time_budget_s,
        cancel,
    )


def _run(  # noqa: PLR0913,PLR0917,PLR0915
    world: OccupancyGrid,
    task: TaskSpec,
    scenario_values: Mapping[str, ParamValue],
    model: Kinematic2DModel,
    settings: Kinematic2DSettings,
    seed: int,
    perception: PerceptionModel,
    path: np.ndarray,
    sim_time_budget_s: float,
    cancel: threading.Event | None,
) -> Trace:
    dt = settings.dt
    v_max = _f(scenario_values, PARAM_SPEED, 0.26)
    t_max = min(sim_time_budget_s, time_limit_s(task, v_max, polyline_length_m(path)))
    max_steps = math.floor(t_max / dt) + 1
    sample_every = max(1, round(1.0 / (settings.sample_hz * dt)))
    n_samples = max(_MIN_TRACE_SAMPLES, (max_steps + sample_every - 1) // sample_every)

    cols: dict[str, Any] = {
        name: np.empty(n_samples, dtype=np.float64)
        for name in (
            "t",
            "gt_x",
            "gt_y",
            "gt_yaw",
            "est_x",
            "est_y",
            "est_yaw",
            "cmd_v",
            "cmd_w",
            "meas_v",
            "meas_w",
            "min_obstacle_dist",
            "roll",
            "pitch",
        )
    }
    contact = np.zeros(n_samples, dtype=np.bool_)
    nav_status = np.zeros(n_samples, dtype=np.int8)

    rng_sensor = make_rng(seed, SENSOR)
    rng_perc = make_rng(seed, PERCEPTION)
    rng_loc = make_rng(seed, LOCALIZATION)

    caster = GridRayCaster(world)
    lidar = Lidar.from_config(caster, model, settings)
    depth = DepthCamera.from_config(caster, model, settings, perception)
    pallet = _pallet(task, path, scenario_values)
    radius = model.robot.footprint_radius_m
    inflate_r = radius + model.costmap.inflation_m
    inflated_static = _global_inflated(world, inflate_r)
    delay_s = _f(scenario_values, PARAM_DELAY_MS, 20.0) / _MS_PER_S
    delay: CommandDelayBuffer[tuple[float, float]] = CommandDelayBuffer(delay_s)
    start = task.start
    state = RobotState(
        x=start.x,
        y=start.y,
        yaw=start.yaw,
        v=0.0,
        w=0.0,
        odom_x=start.x,
        odom_y=start.y,
        odom_yaw=start.yaw,
        meas_v=0.0,
        meas_w=0.0,
    )
    localizer = Localizer(
        x=start.x,
        y=start.y,
        yaw=start.yaw,
        gain=scan_match_gain(
            model,
            _f(scenario_values, PARAM_LIDAR_NOISE, 0.01),
            _f(scenario_values, PARAM_DROPOUT, 0.0),
        ),
    )
    planned: np.ndarray | None = path
    planned_s = path_arclength(path)
    last_plan_t = -math.inf
    replan_period = 1.0 / model.planner.replan_hz
    cmd = (0.0, 0.0)
    sample_i = 0
    last_odom = (state.odom_x, state.odom_y, state.odom_yaw)
    status = NavStatus.ACTIVE
    friction = _f(scenario_values, PARAM_FRICTION, 0.8)
    illuminance = _f(scenario_values, PARAM_ILLUMINANCE, 300.0)
    noise = _f(scenario_values, PARAM_LIDAR_NOISE, 0.01)
    dropout = _f(scenario_values, PARAM_DROPOUT, 0.0)

    for step_i in range(max_steps):
        if cancel is not None and cancel.is_set():
            status = NavStatus.CANCELED
            break
        t = step_i * dt
        pose = (state.x, state.y, state.yaw)
        if t - last_plan_t >= replan_period:
            lidar_ranges = lidar.scan(pose, rng_sensor, noise, dropout, pallet)
            depth_ranges = depth.scan(pose, pallet, illuminance, rng_perc)
            cm = model.costmap
            lidar_cells = (
                cm.lidar_hit_inflation_cells if noise >= cm.lidar_overlay_min_noise_std_m else 0
            )
            plan_grid = overlay_sensor_hits(
                inflated_static,
                pose,
                lidar_ranges if lidar_cells else np.full_like(lidar_ranges, np.nan),
                lidar.beams.angles,
                depth_ranges,
                depth.beams.angles,
                lidar_inflation_cells=lidar_cells,
                depth_inflation_cells=cm.depth_hit_inflation_cells,
            )
            planned = plan_path(
                plan_grid,
                (localizer.x, localizer.y),
                (task.goal.x, task.goal.y),
            )
            planned_s = path_arclength(planned) if planned is not None else planned_s
            last_plan_t = t
            if planned is None:
                status = NavStatus.ABORTED
                cmd = (0.0, 0.0)
        dist = _circle_clearance(world, radius, state.x, state.y, pallet)
        if planned is not None and status is NavStatus.ACTIVE:
            pose_est = (localizer.x, localizer.y, localizer.yaw)
            cmd = pure_pursuit(pose_est, planned, v_max, dist, model, planned_s)
        state = step(state, cmd, dt, model, friction, delay, t)
        odom_delta = (
            state.odom_x - last_odom[0],
            state.odom_y - last_odom[1],
            state.odom_yaw - last_odom[2],
        )
        last_odom = (state.odom_x, state.odom_y, state.odom_yaw)
        localizer.update(odom_delta, (state.x, state.y, state.yaw), rng_loc)
        if status is NavStatus.ACTIVE and _at_goal(state.x, state.y, state.yaw, task):
            status = NavStatus.SUCCEEDED
        if step_i % sample_every == 0 and sample_i < n_samples:
            _record(cols, contact, nav_status, sample_i, t, state, localizer, cmd, dist, status)
            sample_i += 1
        if status in (NavStatus.SUCCEEDED, NavStatus.ABORTED, NavStatus.CANCELED):
            break

    if sample_i == 0:
        _record(cols, contact, nav_status, 0, 0.0, state, localizer, cmd, 0.0, status)
        sample_i = 1
    if sample_i < _MIN_TRACE_SAMPLES:
        _record(
            cols,
            contact,
            nav_status,
            1,
            max(dt, cols["t"][0] + dt),
            state,
            localizer,
            cmd,
            float((contact[0] and 0.0) or 1.0),
            status,
        )
        sample_i = 2
        cols["min_obstacle_dist"][1] = cols["min_obstacle_dist"][0]

    sl = slice(0, sample_i)
    return Trace(
        t=cols["t"][sl],
        gt_x=cols["gt_x"][sl],
        gt_y=cols["gt_y"][sl],
        gt_yaw=cols["gt_yaw"][sl],
        est_x=cols["est_x"][sl],
        est_y=cols["est_y"][sl],
        est_yaw=cols["est_yaw"][sl],
        cmd_v=cols["cmd_v"][sl],
        cmd_w=cols["cmd_w"][sl],
        meas_v=cols["meas_v"][sl],
        meas_w=cols["meas_w"][sl],
        min_obstacle_dist=cols["min_obstacle_dist"][sl],
        contact=contact[sl],
        roll=cols["roll"][sl],
        pitch=cols["pitch"][sl],
        nav_status=nav_status[sl],
        goal_x=task.goal.x,
        goal_y=task.goal.y,
        meta={
            "backend": "kinematic2d",
            "k2d_model_version": model.id,
            "sample_hz": settings.sample_hz,
            "seed": seed,
        },
    )


def _record(  # noqa: PLR0913,PLR0917
    cols: dict[str, Any],
    contact: np.ndarray,
    nav_status: np.ndarray,
    i: int,
    t: float,
    state: RobotState,
    localizer: Localizer,
    cmd: tuple[float, float],
    dist: float,
    status: NavStatus,
) -> None:
    cols["t"][i] = t
    cols["gt_x"][i] = state.x
    cols["gt_y"][i] = state.y
    cols["gt_yaw"][i] = state.yaw
    cols["est_x"][i] = localizer.x
    cols["est_y"][i] = localizer.y
    cols["est_yaw"][i] = localizer.yaw
    cols["cmd_v"][i] = cmd[0]
    cols["cmd_w"][i] = cmd[1]
    cols["meas_v"][i] = state.meas_v
    cols["meas_w"][i] = state.meas_w
    cols["min_obstacle_dist"][i] = dist
    cols["roll"][i] = 0.0
    cols["pitch"][i] = 0.0
    contact[i] = dist <= 0.0
    nav_status[i] = np.int8(status)
