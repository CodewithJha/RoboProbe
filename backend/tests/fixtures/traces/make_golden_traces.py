"""Build analytic golden traces (docs/08 §7). Run as a module to write Parquet files."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from tests.factories import make_trace

from roboprobe.backends import trace_io
from roboprobe.core.types import NavStatus, Trace

DT = 0.1
OUT = Path(__file__).resolve().parent


def _line(*, n: int, speed: float, stop_t: float | None = None) -> dict[str, np.ndarray]:
    t = np.arange(n, dtype=np.float64) * DT
    x = speed * t
    if stop_t is not None:
        x = np.minimum(x, speed * stop_t)
    v = np.full(n, speed)
    if stop_t is not None:
        v = np.where(t <= stop_t, speed, 0.0)
    nav = np.full(n, NavStatus.ACTIVE, dtype=np.int8)
    return {"t": t, "gt_x": x, "est_x": x.copy(), "cmd_v": v, "meas_v": v, "nav_status": nav}


def straight_pass() -> Trace:
    n = 101
    cols = _line(n=n, speed=0.5)
    cols["nav_status"][-1] = NavStatus.SUCCEEDED
    d = np.full(n, 1.0)
    return make_trace(n=n, dt=DT, speed=0.0, goal=(5.0, 0.0), min_obstacle_dist=d, **cols)


def head_on_collision() -> Trace:
    n = 151
    stop = 2.0
    cols = _line(n=n, speed=0.5, stop_t=stop)
    t = cols["t"]
    contact = t >= stop
    d = np.where(contact, 0.0, 1.0)
    return make_trace(
        n=n,
        dt=DT,
        speed=0.0,
        goal=(5.0, 0.0),
        contact=contact,
        min_obstacle_dist=d,
        **cols,
    )


def graze_near_miss() -> Trace:
    trace = straight_pass()
    n = trace.n_samples
    return make_trace(
        n=n,
        dt=DT,
        speed=0.0,
        goal=(5.0, 0.0),
        t=trace.t,
        gt_x=trace.gt_x,
        est_x=trace.est_x,
        cmd_v=trace.cmd_v,
        meas_v=trace.meas_v,
        nav_status=trace.nav_status,
        min_obstacle_dist=np.full(n, 0.05),
    )


def stuck_in_corner() -> Trace:
    n = 151
    cols = _line(n=n, speed=0.0)
    d = np.full(n, 1.0)
    return make_trace(n=n, dt=DT, speed=0.0, goal=(5.0, 0.0), min_obstacle_dist=d, **cols)


def amcl_jump() -> Trace:
    base = straight_pass()
    n = base.n_samples
    return make_trace(
        n=n,
        dt=DT,
        speed=0.0,
        goal=(5.0, 0.0),
        t=base.t,
        gt_x=base.gt_x,
        est_x=base.gt_x + 1.0,
        cmd_v=base.cmd_v,
        meas_v=base.meas_v,
        nav_status=base.nav_status,
        min_obstacle_dist=np.full(n, 1.0),
    )


def nav_abort() -> Trace:
    n = 81
    cols = _line(n=n, speed=0.0)
    cols["gt_x"] = np.zeros(n)
    cols["est_x"] = cols["gt_x"].copy()
    cols["nav_status"][:] = NavStatus.ACTIVE
    cols["nav_status"][-1] = NavStatus.ABORTED
    d = np.full(n, 1.0)
    return make_trace(n=n, dt=DT, speed=0.0, goal=(5.0, 0.0), min_obstacle_dist=d, **cols)


def spin_instability() -> Trace:
    base = straight_pass()
    n = base.n_samples
    return make_trace(
        n=n,
        dt=DT,
        speed=0.0,
        goal=(5.0, 0.0),
        t=base.t,
        gt_x=base.gt_x,
        est_x=base.est_x,
        cmd_v=base.cmd_v,
        meas_v=base.meas_v,
        meas_w=np.full(n, 4.0),
        nav_status=base.nav_status,
        min_obstacle_dist=np.full(n, 1.0),
    )


def oscillation() -> Trace:
    base = straight_pass()
    n = base.n_samples
    w = 0.5 * np.where(np.arange(n) % 2 == 0, 1.0, -1.0)
    return make_trace(
        n=n,
        dt=DT,
        speed=0.0,
        goal=(5.0, 0.0),
        t=base.t,
        gt_x=base.gt_x,
        est_x=base.est_x,
        cmd_v=base.cmd_v,
        cmd_w=w,
        meas_v=base.meas_v,
        nav_status=base.nav_status,
        min_obstacle_dist=np.full(n, 1.0),
    )


TRACES = {
    "straight_pass": straight_pass,
    "head_on_collision": head_on_collision,
    "graze_near_miss": graze_near_miss,
    "stuck_in_corner": stuck_in_corner,
    "amcl_jump": amcl_jump,
    "nav_abort": nav_abort,
    "spin_instability": spin_instability,
    "oscillation": oscillation,
}


def write_all(directory: Path = OUT) -> None:
    """Write each golden trace as zstd Parquet."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, factory in TRACES.items():
        trace_io.write_trace(factory(), directory / f"{name}.parquet")


if __name__ == "__main__":
    write_all()
